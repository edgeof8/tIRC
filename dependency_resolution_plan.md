# Plan: Enhance `ScriptManager.load_scripts()` for Dependency Resolution

**Objective:** Enhance `ScriptManager.load_scripts()` to respect script dependencies defined in `ScriptMetadata`. Scripts should only be loaded if their declared dependencies are already loaded and enabled, or loaded in an order that satisfies these dependencies.

**Background:**
The `ScriptMetadata` class (defined in `script_api_handler.py`) includes a `dependencies: List[str]` field. The `ScriptAPIHandler` has a `check_dependencies()` method. Currently, `ScriptManager.load_scripts()` loads scripts in directory listing order without explicitly checking or ordering by these dependencies. This can lead to runtime errors if a script tries to use functionality from another script that hasn't been loaded yet.

**Proposed Flow (Iterative Dependency Resolution):**

```mermaid
graph TD
    A[ScriptManager.load_scripts()] --> B{Initialization};
    B --> C[Pass 1: Collect Metadata];
    C --> D{Loop through scripts/ directory};
    D --> E{For each .py script (not __init__.py, not disabled)};
    E --> F{Create temporary ScriptAPIHandler};
    F --> G{Extract script_name and dependencies from metadata};
    G --> H{Store in scripts_metadata dict};
    H --> I{Add script_name to script_load_candidates list};
    E --> D;
    D --> J{Pass 2: Iterative Dependency Resolution & Loading};
    J --> K{Initialize loaded_script_names (set) and scripts_to_attempt_load (list)};
    K --> L{Loop: while scripts_to_attempt_load and progress made};
    L --> M{Reset made_progress_in_iteration = False};
    L --> N{Iterate through scripts_to_attempt_load};
    N --> O{For each script_name};
    O --> P{Get dependencies from scripts_metadata};
    P --> Q{Check if all dependencies are in loaded_script_names};
    Q -- Yes --> R{If dependencies met};
    R --> S{Execute actual script loading logic};
    S --> T{Add script_name to loaded_script_names};
    T --> U{Set made_progress_in_iteration = True};
    U --> N;
    Q -- No --> V{If dependencies NOT met};
    V --> W{Append script_name to still_pending_this_round};
    W --> N;
    N --> X{After iterating scripts_to_attempt_load};
    X --> Y{Update scripts_to_attempt_load = still_pending_this_round};
    Y --> L;
    L -- Loop ends --> Z{Post-Loop Check};
    Z --> AA{If scripts_to_attempt_load is not empty};
    AA --> BB{Log errors for unresolvable/circular dependencies};
```

**Detailed Steps for `ScriptManager.load_scripts()`:**

1.  **Initialization:**

    - `scripts_metadata: Dict[str, List[str]] = {}` (script_name -> list_of_dependency_names)
    - `script_load_candidates: List[str] = []` (script_names that are valid files and not disabled)

2.  **Pass 1: Collect Metadata and Initial Candidates:**

    - Loop through `os.listdir(self.scripts_dir)` as currently done.
    - For each valid script file (`.py`, not `__init__.py`, not in `self.disabled_scripts`):
      - `script_name = script_file[:-3]`
      - Add `script_name` to `script_load_candidates`.
      - Temporarily import the module or create a `ScriptAPIHandler` just to access `metadata.dependencies`.
        ```python
        try:
            # A lighter way than full load just for deps:
            # Construct path, spec_from_file_location, module_from_spec
            # Then try to access a well-known variable or a static method if metadata were part of the script class directly.
            # However, ScriptMetadata is loaded by ScriptAPIHandler, so we might need a temp one.
            temp_api = ScriptAPIHandler(self.client_logic_ref, self, script_name) # This loads metadata
            dependencies = temp_api.metadata.dependencies
            scripts_metadata[script_name] = dependencies
            self.logger.debug(f"Script '{script_name}' metadata collected. Dependencies: {dependencies}")
        except Exception as e:
            self.logger.error(f"Failed to collect metadata for script {script_name}: {e}. It will not be loaded if it has dependencies or is a dependency.")
            if script_name in script_load_candidates: script_load_candidates.remove(script_name) # Cannot process
        ```

3.  **Pass 2: Iterative Dependency Resolution and Loading:**

    - `loaded_script_names: Set[str] = set()`
    - `scripts_to_attempt_load: List[str] = list(script_load_candidates)` (make a copy to modify)
    - `max_iterations = len(scripts_to_attempt_load) + 5` (safety break for complex cases)
    - `iterations = 0`
    - `made_progress_in_iteration = True`
    - `while scripts_to_attempt_load and iterations < max_iterations and made_progress_in_iteration:`

      - `made_progress_in_iteration = False`
      - `iterations += 1`
      - `still_pending_this_round: List[str] = []`
      - `for script_name in scripts_to_attempt_load:`

        - `dependencies = scripts_metadata.get(script_name, [])`
        - `deps_met = True`
        - `missing_deps_for_log = []`
        - `for dep_name in dependencies:`
          - If `dep_name not in loaded_script_names`:
            - If `dep_name not in scripts_metadata and dep_name not in self.disabled_scripts`: # Dependency doesn't exist as a loadable script and isn't explicitly disabled
              self.logger.error(f"Script '{script_name}' has an unknown dependency '{dep_name}'. Cannot load '{script_name}'.")
              deps_met = False
              missing_deps_for_log.append(f"{dep_name} (unknown)")
              break
              elif `dep_name in self.disabled_scripts`:
              self.logger.warning(f"Script '{script_name}' depends on disabled script '{dep_name}'. Cannot load '{script_name}'.")
              deps_met = False
              missing_deps_for_log.append(f"{dep_name} (disabled)")
              break
              else: # Dependency exists but not loaded yet
              deps_met = False
              missing_deps_for_log.append(f"{dep_name} (pending)") # No break here, just mark deps_met as False and continue to check other deps for this script
        - `if deps_met:`

          - _(Actual script loading logic as in current `load_scripts`)_

            ```python
            try:
                script_module = importlib.import_module(f"scripts.{script_name}")
                api_handler = ScriptAPIHandler(self.client_logic_ref, self, script_name)
                # Double check dependencies using the actual API handler now that deps should be loaded
                # This uses is_script_enabled which checks self.scripts (already loaded ones)
                satisfied, missing_runtime_deps = api_handler.check_dependencies()
                if not satisfied:
                    self.logger.error(f"Runtime dependency check failed for '{script_name}': Missing {missing_runtime_deps}. Skipping load.")
                    continue # Skip to next script in scripts_to_attempt_load

                if hasattr(script_module, "get_script_instance"):
                    script_instance = script_module.get_script_instance(api_handler)
                    if script_instance:
                        self.scripts[script_name] = script_instance # Add to main dict
                        if hasattr(script_instance, "load") and callable(script_instance.load):
                            script_instance.load()
                        self.logger.info(f"Successfully loaded and initialized script (deps met): {script_name}")
                        loaded_script_names.add(script_name)
                        made_progress_in_iteration = True
                    # ... (else for no script_instance) ...
                # ... (else for no get_script_instance) ...
            except Exception as e:
                self.logger.error(f"Failed to load script {script_name} (even with deps met): {e}", exc_info=True)
            ```

        - `else:`
          - `still_pending_this_round.append(script_name)`
          - If `missing_deps_for_log` contains items not marked "(pending)", it means a hard failure.
          - If any dep is unknown or disabled, this script cannot be loaded.
          - We can log this more definitively here or wait until the end.

      - `scripts_to_attempt_load = still_pending_this_round`

4.  **Post-Loop Check:**
    - `if scripts_to_attempt_load:`
      - `self.logger.error(f"Could not load some scripts due to missing or circular dependencies: {', '.join(scripts_to_attempt_load)}")`
      - For each script in `scripts_to_attempt_load`, log its specific missing dependencies based on `scripts_metadata` and `loaded_script_names`.

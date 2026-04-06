# This file defines how PyOxidizer application building and packaging is
# performed. See PyOxidizer's documentation at
# https://gregoryszorc.com/docs/pyoxidizer/stable/pyoxidizer.html for details
# of this configuration file format.

# Configuration files consist of functions which define build "targets."
# This function creates a Python executable and installs it in a destination
# directory.
def make_exe():
    # Obtain the default PythonDistribution for our build target. We link
    # this distribution into our produced executable and extract the Python
    # standard library from it.
    dist = default_python_distribution()

    # This function creates a `PythonPackagingPolicy` instance, which
    # influences how executables are built and how resources are added to
    # the executable. You can customize the default behavior by assigning
    # to attributes and calling functions.
    policy = dist.make_python_packaging_policy()

    # Enable support for non-classified "file" resources to be added to
    # resource collections. This is needed for shared libraries like OpenBLAS
    # that numpy depends on.
    policy.allow_files = True

    # Control support for loading Python extensions and other shared libraries
    # from memory. This is only supported on Windows and is ignored on other
    # platforms.
    # policy.allow_in_memory_shared_library_loading = True

    # Control whether to generate Python bytecode at various optimization
    # levels. The default optimization level used by Python is 0.
    # policy.bytecode_optimize_level_zero = True
    # policy.bytecode_optimize_level_one = True
    # policy.bytecode_optimize_level_two = True

    # Package all available Python extensions in the distribution.
    # This is needed for packages like numpy that have C extensions.
    policy.extension_module_filter = "all"

    # Package the minimum set of Python extensions in the distribution needed
    # to run a Python interpreter. Various functionality from the Python
    # standard library won't work with this setting! But it can be used to
    # reduce the size of generated executables by omitting unused extensions.
    # policy.extension_module_filter = "minimal"

    # Package Python extensions in the distribution not having additional
    # library dependencies. This will exclude working support for SSL,
    # compression formats, and other functionality.
    # policy.extension_module_filter = "no-libraries"

    # Package Python extensions in the distribution not having a dependency on
    # copyleft licensed software like GPL.
    # policy.extension_module_filter = "no-copyleft"

    # Controls whether the file scanner attempts to classify files and emit
    # resource-specific values.
    # policy.file_scanner_classify_files = True

    # Controls whether `File` instances are emitted by the file scanner.
    # Enable this to ensure shared libraries (.so files) are included.
    policy.file_scanner_emit_files = True

    # Controls the `add_include` attribute of "classified" resources
    # (`PythonModuleSource`, `PythonPackageResource`, etc).
    # Enable this to ensure package resources are included for importlib.resources.
    policy.include_classified_resources = True

    # Toggle whether Python module source code for modules in the Python
    # distribution's standard library are included.
    # policy.include_distribution_sources = False

    # Toggle whether Python package resource files for the Python standard
    # library are included.
    # policy.include_distribution_resources = False

    # Controls the `add_include` attribute of `File` resources.
    # Enable this to include shared libraries and other file resources.
    policy.include_file_resources = True

    # Controls the `add_include` attribute of `PythonModuleSource` not in
    # the standard library.
    # policy.include_non_distribution_sources = True

    # Toggle whether files associated with tests are included.
    # policy.include_test = False

    # Resources are loaded from "in-memory" or "filesystem-relative" paths.
    # The locations to attempt to add resources to are defined by the
    # `resources_location` and `resources_location_fallback` attributes.
    # The former is the first/primary location to try and the latter is
    # an optional fallback.

    # Use filesystem-relative location for resources to allow C extensions
    # (like _cffi_backend used by cryptography) to load properly.
    # C extensions cannot be loaded from memory on Linux/macOS.
    # Use filesystem for both primary and fallback since mixing filesystem
    # primary with in-memory fallback is not supported.
    policy.resources_location = "filesystem-relative:lib"

    # Define a preferred Python extension module variant in the Python distribution
    # to use.
    # policy.set_preferred_extension_module_variant("foo", "bar")

    # Configure policy values to classify files as typed resources.
    # (This is the default.) This ensures package resources are properly
    # classified and accessible via importlib.resources.
    policy.set_resource_handling_mode("classify")

    # Configure policy values to handle files as files and not attempt
    # to classify files as specific types.
    # policy.set_resource_handling_mode("files")

    # This variable defines the configuration of the embedded Python
    # interpreter. By default, the interpreter will run a Python REPL
    # using settings that are appropriate for an "isolated" run-time
    # environment.
    #
    # The configuration of the embedded Python interpreter can be modified
    # by setting attributes on the instance. Some of these are
    # documented below.
    python_config = dist.make_python_interpreter_config()

    # Make the embedded interpreter behave like a `python` process.
    # python_config.config_profile = "python"

    # Set initial value for `sys.path`. If the string `$ORIGIN` exists in
    # a value, it will be expanded to the directory of the built executable.
    # This ensures Python can find modules in the lib directory.
    python_config.module_search_paths = ["$ORIGIN/lib"]

    # Use jemalloc as Python's memory allocator.
    # python_config.allocator_backend = "jemalloc"

    # Use mimalloc as Python's memory allocator.
    # python_config.allocator_backend = "mimalloc"

    # Use snmalloc as Python's memory allocator.
    # python_config.allocator_backend = "snmalloc"

    # Let Python choose which memory allocator to use. (This will likely
    # use the malloc()/free() linked into the program.
    # python_config.allocator_backend = "default"

    # Enable the use of a custom allocator backend with the "raw" memory domain.
    # python_config.allocator_raw = True

    # Enable the use of a custom allocator backend with the "mem" memory domain.
    # python_config.allocator_mem = True

    # Enable the use of a custom allocator backend with the "obj" memory domain.
    # python_config.allocator_obj = True

    # Enable the use of a custom allocator backend with pymalloc's arena
    # allocator.
    # python_config.allocator_pymalloc_arena = True

    # Enable Python memory allocator debug hooks.
    # python_config.allocator_debug = True

    # Automatically calls `multiprocessing.set_start_method()` with an
    # appropriate value when OxidizedFinder imports the `multiprocessing`
    # module.
    # python_config.multiprocessing_start_method = 'auto'

    # Do not call `multiprocessing.set_start_method()` automatically. (This
    # is the default behavior of Python applications.)
    # python_config.multiprocessing_start_method = 'none'

    # Call `multiprocessing.set_start_method()` with explicit values.
    # python_config.multiprocessing_start_method = 'fork'
    # python_config.multiprocessing_start_method = 'forkserver'
    # python_config.multiprocessing_start_method = 'spawn'

    # Control whether `oxidized_importer` is the first importer on
    # `sys.meta_path`.
    # Disable oxidized_importer to allow importlib.resources to work properly
    # with filesystem-relative resources. This is needed for packages like litellm
    # that use importlib.resources.files().
    python_config.oxidized_importer = False

    # Enable the standard path-based importer which attempts to load
    # modules from the filesystem. This is required for C extensions
    # like numpy's OpenBLAS shared libraries to load properly.
    python_config.filesystem_importer = True

    # Set `sys.frozen = False`
    # python_config.sys_frozen = False

    # Set `sys.meipass`
    # python_config.sys_meipass = True

    # Write files containing loaded modules to the directory specified
    # by the given environment variable.
    # python_config.write_modules_directory_env = "/tmp/oxidized/loaded_modules"

    # Evaluate a string as Python code when the interpreter starts.
    # python_config.run_command = "<code>"

    # Run a Python module as __main__ when the interpreter starts.
    # python_config.run_module = "<module>"

    # Run a Python file when the interpreter starts.
    # python_config.run_filename = "/path/to/file"

    # Configure the embedded interpreter to start the Deadend JSON-RPC server,
    # mirroring the console_script entry point
    # `deadend-jsonrpc-server = "deadend_cli.entrypoints:jsonrpc_server"`.
    # The entrypoint function uses typer to parse command-line arguments from sys.argv,
    # so arguments like --debug and --log-file will be properly handled.
    # 
    # Also patch importlib.resources to work with PyOxidizer's filesystem layout
    # by using importlib_resources (backport) or filesystem-based access.
    python_config.run_command = """
import sys
import os
# Patch importlib.resources to work with filesystem-relative resources
try:
    import importlib.resources as resources
    # Monkey-patch resources.files() to work with filesystem layout
    _original_files = resources.files
    def _patched_files(package):
        try:
            return _original_files(package)
        except (ValueError, AttributeError):
            # Fallback: try to find the package on sys.path
            import importlib
            module = importlib.import_module(package)
            if hasattr(module, '__file__') and module.__file__:
                from pathlib import Path
                return Path(module.__file__).parent
            raise
    resources.files = _patched_files
except Exception:
    pass
from deadend_cli.jsonrpc_server import main; main()
"""

    # Produce a PythonExecutable from a Python distribution, embedded
    # resources, and other options. The returned object represents the
    # standalone executable that will be built.
    exe = dist.to_python_executable(
        name="deadend",

        # If no argument passed, the default `PythonPackagingPolicy` for the
        # distribution is used.
        packaging_policy=policy,

        # If no argument passed, the default `PythonInterpreterConfig` is used.
        config=python_config,
    )

    # Install tcl/tk support files to a specified directory so the `tkinter` Python
    # module works.
    # exe.tcl_files_path = "lib"

    # Never attempt to copy Windows runtime DLLs next to the built executable.
    # exe.windows_runtime_dlls_mode = "never"

    # Copy Windows runtime DLLs next to the built executable when they can be
    # located.
    # exe.windows_runtime_dlls_mode = "when-present"

    # Copy Windows runtime DLLs next to the build executable and error if this
    # cannot be done.
    # exe.windows_runtime_dlls_mode = "always"

    # Make the executable a console application on Windows.
    # exe.windows_subsystem = "console"

    # Make the executable a non-console application on Windows.
    # exe.windows_subsystem = "windows"

    # Invoke `pip download` to install a single package using wheel archives
    # obtained via `pip download`. `pip_download()` returns objects representing
    # collected files inside Python wheels. `add_python_resources()` adds these
    # objects to the binary, with a load location as defined by the packaging
    # policy's resource location attributes.
    #exe.add_python_resources(exe.pip_download(["pyflakes==2.2.0"]))

    # Invoke `pip install` with our Python distribution to install a single package.
    # `pip_install()` returns objects representing installed files.
    # `add_python_resources()` adds these objects to the binary, with a load
    # location as defined by the packaging policy's resource location
    # attributes.
    #exe.add_python_resources(exe.pip_install(["appdirs"]))

    # Invoke `pip install` using a requirements file and add the collected resources
    # to our binary.
    #exe.add_python_resources(exe.pip_install(["-r", "requirements.txt"]))

    # Install all external dependencies from pyproject.toml.
    # Note: We exclude workspace packages (deadend-agent, deadend-prompts,
    # deadend-eval, python-sandbox-client)
    # as those are included via read_package_root below.
    exe.add_python_resources(
        exe.pip_install([
            "aiofiles==25.1.0",
            "aiohttp==3.13.5",
            "aiolimiter==1.2.1",
            "asgiref==3.11.1",
            "aiosqlite==0.22.1",
            "beautifulsoup4==4.14.3",
            "cssbeautifier==1.15.4",
            "docker==7.1.0",
            "dotenv==0.9.9",
            "google-genai==1.70.0",
            "httptools==0.7.1",
            "instructor==1.15.1",
            "jsbeautifier==1.15.4",
            "litellm==1.83.0",
            # Note: "logging" is Python's built-in module, no need to install from PyPI
            "lxml==6.0.2",
            "nest-asyncio==1.6.0",
            "numpy==2.2.6",
            "opentelemetry-api==1.39.1",
            "opentelemetry-exporter-otlp==1.39.1",
            "opentelemetry-sdk==1.39.1",
            "playwright==1.58.0",
            "pydantic==2.12.5",
            "pydantic-ai==1.77.0",
            "pydantic-ai-slim[google,openrouter]==1.77.0",
            "pyyaml==6.0.3",
            "readchar==4.2.1",
            "rich==14.3.3",
            "semantic-text-splitter==0.29.0",
            "sqlalchemy==2.0.49",
            "tenacity==9.1.4",
            "tiktoken==0.12.0",
            "toml==0.10.2",
            "toml-rs==0.3.8",
            "tree-sitter-css==0.25.0",
            "tree-sitter-html==0.23.2",
            "tree-sitter-javascript==0.25.0",
            "tree-sitter-markdown==0.5.1",
            "tree-sitter-typescript==0.23.2",
            "typer==0.24.1",
            "jinja2==3.1.6",
            "typing-extensions==4.15.0",
            "python-frontmatter==1.1.0",
        ])
    )

    # Read Python files from a local directory and add them to our embedded
    # context, taking just the resources belonging to the `foo` and `bar`
    # Python packages.
    #exe.add_python_resources(exe.read_package_root(
    #    path="/src/mypackage",
    #    packages=["foo", "bar"],
    #))

    # Read Python files from the local workspace and add them to our embedded
    # context so the binary contains the full Deadend CLI codebase.
    #
    # These paths and package names mirror the Hatch wheel build configuration
    # in `deadend_cli/pyproject.toml` (tool.hatch.build.targets.wheel.packages).
    exe.add_python_resources(
        exe.read_package_root(
            # Contains the `deadend_cli` package.
            path = "../src",
            packages = ["deadend_cli"],
        )
    )

    exe.add_python_resources(
        exe.read_package_root(
            # Contains the `deadend_agent` package.
            path = "../deadend_agent/src",
            packages = ["deadend_agent"],
        )
    )

    exe.add_python_resources(
        exe.read_package_root(
            # Contains the `deadend_prompts` package and its Jinja2 templates.
            path = "../deadend_prompts/src",
            packages = ["deadend_prompts"],
        )
    )

    exe.add_python_resources(
        exe.read_package_root(
            # Contains the `deadend_eval` package.
            path = "../deadend_eval/src",
            packages = ["deadend_eval"],
        )
    )

    exe.add_python_resources(
        exe.read_package_root(
            # Contains the `python_sandbox_client` package used by the Python
            # interpreter tool. The worker TypeScript files are copied into the
            # final install layout by the release workflow.
            path = "../simple-python-interpreter-sandbox",
            packages = ["python_sandbox_client"],
        )
    )

    # Discover Python files from a virtualenv and add them to our embedded
    # context.
    #exe.add_python_resources(exe.read_virtualenv(path="/path/to/venv"))

    # Filter all resources collected so far through a filter of names
    # in a file.
    #exe.filter_resources_from_files(files=["/path/to/filter-file"])

    # Return our `PythonExecutable` instance so it can be built and
    # referenced by other consumers of this target.
    return exe

def make_embedded_resources(exe):
    return exe.to_embedded_resources()

def make_install(exe):
    # Create an object that represents our installed application file layout.
    files = FileManifest()

    # Add the generated executable to our install layout in the root directory.
    files.add_python_resource(".", exe)
    
    # Note: The wrapper script (deadend.sh) should be copied manually to the install directory
    # after building. It sets LD_LIBRARY_PATH to include the lib directory so that
    # shared libraries (like OpenBLAS for numpy) can be found.
    # 
    # After building, run:
    # cp deadend.sh build/x86_64-unknown-linux-gnu/debug/install/deadend.sh
    # chmod +x build/x86_64-unknown-linux-gnu/debug/install/deadend.sh

    return files

def make_msi(exe):
    # See the full docs for more. But this will convert your Python executable
    # into a `WiXMSIBuilder` Starlark type, which will be converted to a Windows
    # .msi installer when it is built.
    return exe.to_wix_msi_builder(
        # Simple identifier of your app.
        "myapp",
        # The name of your application.
        "My Application",
        # The version of your application.
        "1.0",
        # The author/manufacturer of your application.
        "Alice Jones"
    )


# Dynamically enable automatic code signing.
def register_code_signers():
    # You will need to run with `pyoxidizer build --var ENABLE_CODE_SIGNING 1` for
    # this if block to be evaluated.
    if not VARS.get("ENABLE_CODE_SIGNING"):
        return

    # Use a code signing certificate in a .pfx/.p12 file, prompting the
    # user for its path and password to open.
    # pfx_path = prompt_input("path to code signing certificate file")
    # pfx_password = prompt_password(
    #     "password for code signing certificate file",
    #     confirm = True
    # )
    # signer = code_signer_from_pfx_file(pfx_path, pfx_password)

    # Use a code signing certificate in the Windows certificate store, specified
    # by its SHA-1 thumbprint. (This allows you to use YubiKeys and other
    # hardware tokens if they speak to the Windows certificate APIs.)
    # sha1_thumbprint = prompt_input(
    #     "SHA-1 thumbprint of code signing certificate in Windows store"
    # )
    # signer = code_signer_from_windows_store_sha1_thumbprint(sha1_thumbprint)

    # Choose a code signing certificate automatically from the Windows
    # certificate store.
    # signer = code_signer_from_windows_store_auto()

    # Activate your signer so it gets called automatically.
    # signer.activate()


# Call our function to set up automatic code signers.
register_code_signers()

# Tell PyOxidizer about the build targets defined above.
register_target("exe", make_exe)
register_target("resources", make_embedded_resources, depends=["exe"], default_build_script=True)
register_target("install", make_install, depends=["exe"], default=True)
register_target("msi_installer", make_msi, depends=["exe"])

# Resolve whatever targets the invoker of this configuration file is requesting
# be resolved.
resolve_targets()

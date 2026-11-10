def get_wine_compatible_path(filename: str = "openem_solve.fem") -> str:
    """Get a file path that both Python and Wine/FEMM can access.

    On macOS/Linux with Wine, FEMM runs inside Wine and sees the filesystem
    through drive mappings. The Z: drive maps to the Unix root (/), so
    a file at /Users/mac/wine_femm_tmp/solve.fem is accessible in Wine as
    Z:\\Users\\mac\\wine_femm_tmp\\solve.fem.

    However, pyFEMM's mi_saveas() handles this translation internally on
    newer versions. The key fix is to use a path under the Wine prefix's
    drive_c directory, which is always accessible from both sides.

    Root cause of Sprint 2 bug: pyFEMM used Python's tempfile.mkdtemp()
    which creates files in /tmp or /var/folders on macOS. Wine's Z: drive
    mapping should translate these, but the path escaping fails for paths
    containing special characters or deeply nested temp directories.

    Fix: Save to ~/.wine/drive_c/openem_tmp/ which is C:\\openem_tmp\\ in
    Wine — a short, clean path with no special characters.

    Args:
        filename: Name of the .fem file

    Returns:
        Absolute path accessible from both Python and Wine
    """
    import os
    import platform

    if platform.system() == "Windows":
        # On Windows, use temp directory directly
        import tempfile
        tmp_dir = os.path.join(tempfile.gettempdir(), "openem")
        os.makedirs(tmp_dir, exist_ok=True)
        return os.path.join(tmp_dir, filename)

    # macOS/Linux: use Wine prefix's drive_c for reliable path translation.
    # If the Wine prefix doesn't exist (e.g. Linux CI without Wine), fall back
    # to a plain Unix tempdir so path utilities (os.path.dirname etc.) work.
    wine_prefix = os.environ.get("WINEPREFIX", os.path.expanduser("~/.wine"))
    wine_c_dir = os.path.join(wine_prefix, "drive_c", "openem_tmp")

    if os.path.isdir(os.path.dirname(wine_c_dir)):
        # Wine prefix exists on this machine — create our subdir and return
        # the Windows-style C:\ path that FEMM.exe understands natively.
        # pyFEMM sends this path to FEMM via Lua; FEMM under Wine maps
        # "C:\openem_tmp\file.fem" directly to drive_c without Z: translation.
        os.makedirs(wine_c_dir, exist_ok=True)
        return "C:\\\\openem_tmp\\\\" + filename

    # No Wine prefix (Linux CI, Docker, etc.) — use a real Unix tempdir.
    # FEMM won't be invoked here; this path is only used for path-utility
    # tests and dry-run geometry draws.
    import tempfile
    unix_fallback = os.path.join(tempfile.gettempdir(), "openem_tmp")
    os.makedirs(unix_fallback, exist_ok=True)
    return os.path.join(unix_fallback, filename)

def get_native_path_from_wine_path(path: str) -> str:
    """Convert a Wine-visible ``C:\\...`` path back to the native host path.

    FEMM APIs under Wine often need Windows-style ``C:\\openem_tmp\\file.fem``
    paths, while Python filesystem calls such as ``shutil.copy2`` need the host
    path inside the Wine prefix. This helper bridges the two representations.
    """
    import os
    import platform

    if platform.system() == "Windows":
        return path

    normalized = path.replace("\\\\", "\\")
    if len(normalized) >= 3 and normalized[1:3] == ":\\":
        drive_letter = normalized[0].lower()
        rel = normalized[3:].replace("\\", os.sep)
        wine_prefix = os.environ.get("WINEPREFIX", os.path.expanduser("~/.wine"))
        return os.path.join(wine_prefix, f"drive_{drive_letter}", rel)

    return path

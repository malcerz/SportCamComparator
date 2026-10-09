def test_os_is_imported_in_main():
    with open("src/main.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert "import os" in content, "Missing import os in main.py"
    
    # Check if os is globally available in the module by importing it
    import main
    assert hasattr(main, 'os'), "os module not available in main namespace"

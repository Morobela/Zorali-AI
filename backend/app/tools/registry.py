from app.tools.file_tools import read_file, write_file
from app.tools.git_tools import git_status
from app.tools.code_sandbox import CodeSandbox

sandbox = CodeSandbox()

def get_all_tools():
    return {
        'read_file': read_file,
        'write_file': write_file,
        'git_status': git_status,
        'run_python': sandbox.run_python,
    }

#!/usr/bin/env python

import ast
import os
import sys

currentDir = os.getcwd()
buildDir = 'target/site/'
sphinxPath = 'target/sphinx/'
MINIMUM_DOC_LENGTH = 10


def get_repo_root_dir():
    doc_dir = os.path.dirname(__file__)
    src_dir = os.path.realpath(os.path.join(doc_dir, os.pardir))
    return src_dir

def get_sphinx_source_dir():
    repo_dir = get_repo_root_dir()
    return os.path.join(repo_dir, 'doc', 'sphinx', 'source', '')

def get_sphinx_commands_dir():
    sphinx_src_dir = get_sphinx_source_dir()
    return os.path.join(sphinx_src_dir, 'fw_docs', 'commands', '')

def get_sphinx_mocks_dir():
    sphinx_src_dir = get_sphinx_source_dir()
    return os.path.join(sphinx_src_dir, 'fw_docs', 'mocks', '')


def get_cmd_string():
    """
    Creates the string listing all AT commands in Spinx-friendly format.
    Note: ATCli class cannot be imported as it imports litpcli and core.
    """
    def get_atcli_nodes(module):
        for node in module.body:
            if isinstance(node, ast.ClassDef) and node.name == "ATCli":
                funcs = [func for func in node.body if isinstance(
                        func, ast.FunctionDef)]
                return funcs

    def get_atcli_init_node(atcli_nodes):
        for atcli_node in atcli_nodes:
            if atcli_node.name == "__init__":
                return atcli_node.body

    def get_atcli_cmds_dict(atcli_nodes):
        init_node = get_atcli_init_node(atcli_nodes)
        for init_node in init_node:
            if isinstance(init_node, ast.Assign) and \
                    init_node.targets[0].attr == "commands":
                return convert_ast_dict_to_dict(init_node.value)

    def convert_ast_dict_to_dict(ast_dict):
        converted = {}
        for index, cmd in enumerate(ast_dict.keys):
            converted[cmd.s] = ast_dict.values[index].attr
        return converted

    helpstr = "Available ATRunner Commands\n"
    helpstr += "===========================\n\n"

    # 1. Read atcli.py module and parse to ast format
    cli_module_path = os.path.join(
        get_repo_root_dir(),
        'src',
        'litpats',
        'atcli.py'
    )
    with open(cli_module_path) as atcli_file:
        contents = atcli_file.read()
    module = ast.parse(contents)

    # 2. Build { function_name : (docstring, args) } dict
    atcli_nodes = get_atcli_nodes(module)
    functions_dict = {}
    for node in atcli_nodes:
        functions_dict[node.name] = (ast.get_docstring(node, clean=False),
                [name.id for name in node.args.args])

    # 3. Build {command_name : function_name } dict
    commands_dict = get_atcli_cmds_dict(atcli_nodes)

    # 4. Iterate over sorted command_names and build string
    for command, function_name in sorted(commands_dict.items()):
        docstring = functions_dict[function_name][0]
        cmd_args = functions_dict[function_name][1]

        helpstr += "**{0}**:\n    Usage: {1} {2}\n \n".format(command,
                command, " ".join([cmd_arg for cmd_arg in cmd_args[1:]]))
        helpstr += "    {0}\n\n".format(docstring or '')

    return helpstr

def get_mock_docs():
    # Import the mocks and patches
    __import__('litpats.mocking')
    __import__('litpats.mocking.mocks')
    __import__('litpats.mocking.patches')

    mock_registry = sys.modules['litpats.mocking'].mock_registry
    patch_registry = sys.modules['litpats.mocking'].patch_registry

    mocks_documentation = "Core Mocking Documentation\n"
    mocks_documentation += "==========================\n\n"

    mocks_documentation += "Core Mocks\n"
    mocks_documentation += "----------\n\n"
    for mock_qualname in sorted(list(mock_registry)):
        mock_doc = mock_registry[mock_qualname].__doc__

        if not mock_doc or len(mock_doc) < MINIMUM_DOC_LENGTH:
            raise SystemError(
                "The mock for \"%s\" is not documented!" % mock_qualname
            )

        mocks_documentation += "**{0}**:\n\n  {1}\n".format(
            mock_qualname, mock_registry[mock_qualname].__doc__
        )

    mocks_documentation += "\n\n"
    mocks_documentation += "Core Patches\n"
    mocks_documentation += "------------\n\n"
    for patch_qualname in sorted(list(patch_registry)):
        patch_doc = patch_registry[patch_qualname].__doc__
        if not patch_doc or len(patch_doc) < MINIMUM_DOC_LENGTH:
            raise SystemError(
                "The patch for \"%s\" is not documented!" % patch_qualname
            )
        mocks_documentation += "**{0}**:\n\n  {1}\n".format(
            patch_qualname, patch_registry[patch_qualname].__doc__
        )

    return mocks_documentation

def setupPythonPath(*paths):
    p = []
    for path in paths:
        sphinxAbsPath = os.path.abspath(os.path.join(currentDir, path))
        p.append(sphinxAbsPath)
    sys.path[:0] = p


if __name__ == '__main__':

    src_dir = os.path.join(get_repo_root_dir(), 'src')
    sphinx_dir = os.path.join(
        get_repo_root_dir(),
        'ERIClitpatrunner_CXP9030558', 'target', 'sphinx'
    )
    setupPythonPath(src_dir, sphinx_dir)

    try:
        cmd_list = get_cmd_string()
        mocks_rst = get_mock_docs()

        command_list_dir = get_sphinx_commands_dir()
        commands_rst_path = os.path.join(command_list_dir, 'commands.rst')

        if not os.path.exists(command_list_dir):
            os.mkdir(command_list_dir)

        with open(commands_rst_path, 'w') as commands_rst_file:
            commands_rst_file.write(cmd_list)

        mocks_list_dir = get_sphinx_mocks_dir()
        mocks_rst_path = os.path.join(mocks_list_dir, 'core_mocking.rst')
        if not os.path.exists(mocks_list_dir):
            os.mkdir(mocks_list_dir)

        with open(mocks_rst_path, 'w') as mocks_rst_file:
            mocks_rst_file.write(mocks_rst)

    except Exception as e:
        import traceback; traceback.print_exc()
        print "Generation of method list failed, Skipping"



    from sphinx import cmdline
    cmdline.main([
        '-a',
        os.path.abspath(os.path.join(currentDir, get_sphinx_source_dir())),
        os.path.abspath(os.path.join(currentDir, buildDir))
    ])

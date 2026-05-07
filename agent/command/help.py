from __future__ import annotations

"""集中维护主菜单和对话窗口的帮助文本。"""


def console_help_text() -> str:
    """返回主菜单 help/? 显示的命令说明。"""
    return """
Commands:
  chat                                                              Enter chat flow with memory window selection
  rag-list [rag_id|number]                                          List RAG library statistics
  rag-list -a                                                       List all RAG library statistics
  rag-show <rag_id|number>                                          Show documents in one RAG library
  rag-show -a                                                       Show documents in all RAG libraries
  rag-new [rag_id]                                                  Create a RAG library
  rag-add <file_path|dir> <rag_id|number> [replace|append|fail]     Add file(s) to a RAG library, default method is replace
  rag-add -a <file_path|dir> [replace|append|fail]                  Add file(s) to every existing RAG library, default method is replace
  rag-remove <source> [rag_id|number]                               Delete source from one/all RAG libraries, keeping libraries
  rag-remove -a [rag_id|number]                                     Clear one/all RAG libraries, keeping libraries
  rag-delete <source> [rag_id|number]                               Delete source, and delete the library if it becomes empty
  rag-delete -a [rag_id|number]                                     Delete one/all RAG libraries
  rag-search <query> [rag_id|number]                                Search one RAG library, or all libraries if omitted
  db-list [table|number]                                            List table schema/statistics
  db-list -a                                                        List all table schema/statistics
  db-show <table|number>                                            Show rows in one table
  db-show -a                                                        Show rows in all tables
  db-add <table_file|dir> [replace|append|fail]                     Add table file(s) to the SQLite database, default method is replace
  db-delete <table|number>                                          Delete a table by name or db-list number
  db-delete -a                                                      Delete all imported tables
  db-query <sql>                                                    Run a read-only SELECT/WITH query
  deps-list [window_id|number]                                      List dependency request statistics
  deps-list -a                                                      List all dependency request statistics
  deps-show [window_id|number]                                      Show dependency requests for one/all memory windows
  deps-show -a                                                      Show all memory windows and dependency requests
  deps-install <module|package>                                     Install one dependency by module/package name
  deps-install -a [window_id|number]                                Install dependencies in one/all windows
  deps-ignore <module|package>                                      Ignore this dependency in all memory windows
  deps-ignore <module|package> <window_id|number>                   Ignore this dependency in one window list
  deps-ignore -a [window_id|number]                                 Ignore dependencies in one/all windows
  memory-list [session_id|number]                                   List one/all memory windows
  memory-list -a                                                    List all memory windows
  memory-show <session_id|number>                                   Show conversation memory for a window
  memory-show -a                                                    Show conversation memory for all windows
  memory-new [session_id]                                           Create a new memory window
  memory-clear <session_id|number>                                  Clear turns and dependency requests in a memory window
  memory-clear -a                                                   Clear turns and dependency requests in all memory windows
  memory-delete <session_id|number>                                 Delete a memory window and related records
  memory-delete -a                                                  Delete all memory windows and related records
  libreoffice-check                                                 Check LibreOffice path and update .env if detected
  libreoffice-install                                               Detect or install LibreOffice and update .env
  help / ?                                                          Show this help
  exit / quit                                                       Exit the program
""".strip()


def task_window_help_text() -> str:
    """返回 task[...] 对话窗口 help/? 显示的命令说明。"""
    return """
Task window commands:
  <task text>                                 Send task to DeepSeek
  deps-list                                   List dependency request statistics for this memory window
  deps-show                                   Show dependency requests for this memory window
  deps-install <module|package|number>        Install one dependency request in this window
  deps-install -a                             Install all dependency requests in this window
  deps-ignore <module|package|number>         Ignore one dependency request in this window
  deps-ignore -a                              Ignore all dependency requests in this window
  libreoffice-check                           Check LibreOffice path and update .env if detected
  libreoffice-install                         Detect or install LibreOffice and update .env
  help / ?                                    Show this help
  exit / quit                                 Return to memory window selection
""".strip()

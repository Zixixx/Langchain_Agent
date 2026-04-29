from __future__ import annotations

"""集中维护主菜单和对话窗口的帮助文本。"""


def console_help_text() -> str:
    """返回主菜单 help/? 显示的命令说明。"""
    return """
Commands:
  chat                                              Enter DeepSeek chat flow with memory window selection
  rag-list                                          List documents stored in the RAG knowledge base
  rag-add <file_path|dir>                           Add text file(s) to the RAG knowledge base
  rag-add <file_path|dir> append|replace|fail       Choose a method to add text file(s) to the RAG knowledge base
  rag-delete <source>                               Delete RAG chunks by source
  rag-search <query>                                Search the RAG knowledge base
  db-list                                           List database tables and columns
  db-add <csv_path|dir>                             Import CSV file(s) into SQLite
  db-add <csv_path|dir> append|replace|fail         Choose a method to import CSV file(s) into SQLite
  db-delete <table>                                 Delete a table from the CSV SQLite database
  db-query <sql>                                    Run a read-only SELECT/WITH query
  deps-list                                         List dependency request lists for all memory windows
  deps-install <module>                             Install one dependency by module/package name
  deps-install -a <window-number|window-id>         Install all dependencies in one window list
  deps-ignore <module>                              Ignore this dependency in all memory windows
  deps-ignore <module> <window-number|window-id>    Ignore this dependency in one window list
  deps-ignore -a <window-number|window-id>          Ignore all dependencies in one window list
  memory-list                                       List memory windows
  memory-new [session_id]                           Create a new memory window
  memory-show <session_id>                          Show conversation memory for a window
  memory-clear <session_id>                         Clear messages in a memory window
  memory-delete <session_id>                        Delete a memory window and related records
  help / ?                                          Show this help
  exit / quit                                       Exit the program
""".strip()


def task_window_help_text() -> str:
    """返回 task[...] 对话窗口 help/? 显示的命令说明。"""
    return """
Task window commands:
  <task text>                 Send task to DeepSeek
  deps-list                   List dependency requests for this memory window
  deps-install <module|number>
                              Install one dependency request in this window
  deps-install -a             Install all dependency requests in this window
  deps-ignore <module|number>
                              Ignore one dependency request in this window
  deps-ignore -a              Ignore all dependency requests in this window
  help / ?                    Show this help
  exit / quit                 Return to memory window selection
""".strip()

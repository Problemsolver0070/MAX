"""Native tool implementations for Max.

Call ``register_all_native_tools(provider)`` to register every built-in tool.
"""

from __future__ import annotations

from max.tools.native.aws_tools import (
    TOOL_DEFINITIONS as AWS_TOOLS,
)
from max.tools.native.aws_tools import (
    handle_aws_cloudwatch_query,
    handle_aws_ec2_list,
    handle_aws_ec2_manage,
    handle_aws_lambda_invoke,
    handle_aws_s3_delete,
    handle_aws_s3_get,
    handle_aws_s3_list,
    handle_aws_s3_put,
)
from max.tools.native.browser_tools import (
    TOOL_DEFINITIONS as BROWSER_TOOLS,
)
from max.tools.native.browser_tools import (
    handle_browser_click,
    handle_browser_evaluate,
    handle_browser_fill_form,
    handle_browser_get_content,
    handle_browser_navigate,
    handle_browser_screenshot,
    handle_browser_type,
)
from max.tools.native.calendar_tools import (
    TOOL_DEFINITIONS as CALENDAR_TOOLS,
)
from max.tools.native.calendar_tools import (
    handle_calendar_create_event,
    handle_calendar_delete_event,
    handle_calendar_list_events,
    handle_calendar_update_event,
)
from max.tools.native.code_tools import (
    TOOL_DEFINITIONS as CODE_TOOLS,
)
from max.tools.native.code_tools import (
    handle_code_ast_parse,
    handle_code_dependencies,
    handle_code_format,
    handle_code_lint,
    handle_code_test,
)
from max.tools.native.data_tools import (
    TOOL_DEFINITIONS as DATA_TOOLS,
)
from max.tools.native.data_tools import (
    handle_data_export,
    handle_data_load,
    handle_data_query,
    handle_data_summarize,
    handle_data_transform,
)
from max.tools.native.database_tools import (
    TOOL_DEFINITIONS as DATABASE_TOOLS,
)
from max.tools.native.database_tools import (
    handle_database_postgres_execute,
    handle_database_postgres_query,
    handle_database_redis_get,
    handle_database_redis_set,
    handle_database_sqlite_execute,
    handle_database_sqlite_query,
)
from max.tools.native.docker_tools import (
    TOOL_DEFINITIONS as DOCKER_TOOLS,
)
from max.tools.native.docker_tools import (
    handle_docker_build,
    handle_docker_compose,
    handle_docker_list_containers,
    handle_docker_logs,
    handle_docker_run,
    handle_docker_stop,
)
from max.tools.native.document_tools import (
    TOOL_DEFINITIONS as DOCUMENT_TOOLS,
)
from max.tools.native.document_tools import (
    handle_document_parse_json,
    handle_document_read_pdf,
    handle_document_read_spreadsheet,
    handle_document_write_csv,
    handle_document_write_spreadsheet,
)
from max.tools.native.email_tools import (
    TOOL_DEFINITIONS as EMAIL_TOOLS,
)
from max.tools.native.email_tools import (
    handle_email_list_folders,
    handle_email_read,
    handle_email_search,
    handle_email_send,
)
from max.tools.native.file_tools import (
    TOOL_DEFINITIONS as FILE_TOOLS,
)
from max.tools.native.file_tools import (
    handle_directory_list,
    handle_file_delete,
    handle_file_edit,
    handle_file_glob,
    handle_file_read,
    handle_file_write,
)
from max.tools.native.git_ext_tools import (
    TOOL_DEFINITIONS as GIT_EXT_TOOLS,
)
from max.tools.native.git_ext_tools import (
    handle_git_branch,
    handle_git_clone,
    handle_git_pr_create,
    handle_git_push,
)
from max.tools.native.git_tools import (
    TOOL_DEFINITIONS as GIT_TOOLS,
)
from max.tools.native.git_tools import (
    handle_git_commit,
    handle_git_diff,
    handle_git_log,
    handle_git_status,
)
from max.tools.native.media_tools import (
    TOOL_DEFINITIONS as MEDIA_TOOLS,
)
from max.tools.native.media_tools import (
    handle_media_audio_transcribe,
    handle_media_image_convert,
    handle_media_image_info,
    handle_media_image_resize,
    handle_media_video_info,
)
from max.tools.native.process_tools import (
    TOOL_DEFINITIONS as PROCESS_TOOLS,
)
from max.tools.native.process_tools import (
    handle_process_list,
)
from max.tools.native.scraping_tools import (
    TOOL_DEFINITIONS as SCRAPING_TOOLS,
)
from max.tools.native.scraping_tools import (
    handle_web_extract_links,
    handle_web_scrape,
    handle_web_search,
)
from max.tools.native.search_tools import (
    TOOL_DEFINITIONS as SEARCH_TOOLS,
)
from max.tools.native.search_tools import (
    handle_grep_search,
)
from max.tools.native.server_tools import (
    TOOL_DEFINITIONS as SERVER_TOOLS,
)
from max.tools.native.server_tools import (
    handle_server_service_status,
    handle_server_ssh_execute,
    handle_server_system_info,
)
from max.tools.native.shell_tools import (
    TOOL_DEFINITIONS as SHELL_TOOLS,
)
from max.tools.native.shell_tools import (
    handle_shell_execute,
)
from max.tools.native.web_tools import (
    TOOL_DEFINITIONS as WEB_TOOLS,
)
from max.tools.native.web_tools import (
    handle_http_fetch,
    handle_http_request,
)
from max.tools.providers.native import NativeToolProvider

_HANDLER_MAP = {
    "code.ast_parse": handle_code_ast_parse,
    "code.lint": handle_code_lint,
    "code.format": handle_code_format,
    "code.test": handle_code_test,
    "code.dependencies": handle_code_dependencies,
    "file.read": handle_file_read,
    "file.write": handle_file_write,
    "file.edit": handle_file_edit,
    "directory.list": handle_directory_list,
    "file.glob": handle_file_glob,
    "file.delete": handle_file_delete,
    "shell.execute": handle_shell_execute,
    "git.status": handle_git_status,
    "git.diff": handle_git_diff,
    "git.log": handle_git_log,
    "git.commit": handle_git_commit,
    "http.fetch": handle_http_fetch,
    "http.request": handle_http_request,
    "process.list": handle_process_list,
    "grep.search": handle_grep_search,
    "docker.list_containers": handle_docker_list_containers,
    "docker.run": handle_docker_run,
    "docker.stop": handle_docker_stop,
    "docker.logs": handle_docker_logs,
    "docker.build": handle_docker_build,
    "docker.compose": handle_docker_compose,
    "database.postgres_query": handle_database_postgres_query,
    "database.postgres_execute": handle_database_postgres_execute,
    "database.sqlite_query": handle_database_sqlite_query,
    "database.sqlite_execute": handle_database_sqlite_execute,
    "database.redis_get": handle_database_redis_get,
    "database.redis_set": handle_database_redis_set,
    "document.read_pdf": handle_document_read_pdf,
    "document.read_spreadsheet": handle_document_read_spreadsheet,
    "document.write_csv": handle_document_write_csv,
    "document.write_spreadsheet": handle_document_write_spreadsheet,
    "document.parse_json": handle_document_parse_json,
    "web.scrape": handle_web_scrape,
    "web.extract_links": handle_web_extract_links,
    "web.search": handle_web_search,
    "email.send": handle_email_send,
    "email.read": handle_email_read,
    "email.search": handle_email_search,
    "email.list_folders": handle_email_list_folders,
    "media.image_resize": handle_media_image_resize,
    "media.image_convert": handle_media_image_convert,
    "media.image_info": handle_media_image_info,
    "media.audio_transcribe": handle_media_audio_transcribe,
    "media.video_info": handle_media_video_info,
    "data.load": handle_data_load,
    "data.query": handle_data_query,
    "data.summarize": handle_data_summarize,
    "data.transform": handle_data_transform,
    "data.export": handle_data_export,
    "calendar.list_events": handle_calendar_list_events,
    "calendar.create_event": handle_calendar_create_event,
    "calendar.update_event": handle_calendar_update_event,
    "calendar.delete_event": handle_calendar_delete_event,
    "browser.navigate": handle_browser_navigate,
    "browser.click": handle_browser_click,
    "browser.type": handle_browser_type,
    "browser.screenshot": handle_browser_screenshot,
    "browser.get_content": handle_browser_get_content,
    "browser.fill_form": handle_browser_fill_form,
    "browser.evaluate": handle_browser_evaluate,
    "aws.s3_list": handle_aws_s3_list,
    "aws.s3_get": handle_aws_s3_get,
    "aws.s3_put": handle_aws_s3_put,
    "aws.s3_delete": handle_aws_s3_delete,
    "aws.ec2_list": handle_aws_ec2_list,
    "aws.ec2_manage": handle_aws_ec2_manage,
    "aws.lambda_invoke": handle_aws_lambda_invoke,
    "aws.cloudwatch_query": handle_aws_cloudwatch_query,
    "git.clone": handle_git_clone,
    "git.branch": handle_git_branch,
    "git.push": handle_git_push,
    "git.pr_create": handle_git_pr_create,
    "server.system_info": handle_server_system_info,
    "server.ssh_execute": handle_server_ssh_execute,
    "server.service_status": handle_server_service_status,
}

ALL_TOOL_DEFINITIONS = (
    AWS_TOOLS
    + BROWSER_TOOLS
    + CALENDAR_TOOLS
    + CODE_TOOLS
    + DATA_TOOLS
    + DATABASE_TOOLS
    + DOCKER_TOOLS
    + DOCUMENT_TOOLS
    + EMAIL_TOOLS
    + FILE_TOOLS
    + GIT_TOOLS
    + GIT_EXT_TOOLS
    + MEDIA_TOOLS
    + PROCESS_TOOLS
    + SCRAPING_TOOLS
    + SEARCH_TOOLS
    + SERVER_TOOLS
    + SHELL_TOOLS
    + WEB_TOOLS
)


def register_all_native_tools(provider: NativeToolProvider) -> None:
    """Register all built-in native tools on the given provider."""
    for tool_def in ALL_TOOL_DEFINITIONS:
        handler = _HANDLER_MAP.get(tool_def.tool_id)
        if handler:
            provider.register_tool(tool_def, handler)

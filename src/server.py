import asyncio
import logging
import os
import sys
from typing import List, Optional, Dict, Any
import requests
from mcp.server import Server
from mcp.types import Tool, TextContent, Prompt, PromptMessage, GetPromptResult
from mcp.server.stdio import stdio_server
from mcp.server.models import InitializationOptions

# 设置日志级别为 DEBUG，显示更多信息
logging.basicConfig(
    level=logging.DEBUG,  # 改为 DEBUG 级别
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("dingding_mcp_server")

class DingTalkAPIError(Exception):
    """钉钉 API 错误"""
    def __init__(self, message: str, error_code: int, error_msg: str):
        self.error_code = error_code
        self.error_msg = error_msg
        super().__init__(f"{message}: {error_msg} (code: {error_code})")

class DingdingMCPServer:
    def __init__(self):
        logger.debug("Initializing DingdingMCPServer...")
        self.base_url = "https://oapi.dingtalk.com"
        self.access_token = None
        self._session = requests.Session()
        self.app = Server("dingding-mcp")
        logger.debug("Created MCP Server instance with name: dingding-mcp")
        self.setup_tools()
        self.setup_prompts()
        logger.debug("Server initialization completed")

    def _make_request(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """发送 HTTP 请求并处理通用错误"""
        logger.debug(f"Making request to URL: {url} with params: {params}")
        try:
            response = self._session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            logger.debug(f"Response received: {data}")
            
            if data.get("errcode", 0) != 0:
                logger.error(f"DingTalk API error: {data}")
                raise DingTalkAPIError(
                    "DingTalk API error",
                    data.get("errcode", -1),
                    data.get("errmsg", "Unknown error")
                )
            
            return data
        except requests.RequestException as e:
            logger.error(f"HTTP request failed: {str(e)}", exc_info=True)
            raise DingTalkAPIError("HTTP request failed", -1, str(e))
        except ValueError as e:
            logger.error(f"Invalid JSON response: {str(e)}", exc_info=True)
            raise DingTalkAPIError("Invalid JSON response", -1, str(e))

    def get_access_token(self) -> str:
        """获取钉钉access token"""
        logger.debug("Attempting to get access token...")
        try:
            appkey = os.environ.get("DINGDING_APP_KEY")
            appsecret = os.environ.get("DINGDING_APP_SECRET")
            
            logger.debug(f"Using APP_KEY: {appkey[:4]}*** and APP_SECRET: {appsecret[:4]}***")
            
            if not all([appkey, appsecret]):
                logger.error("Missing DingTalk API credentials in environment variables")
                raise ValueError("Missing DingTalk API credentials in environment variables")
            
            url = f"{self.base_url}/gettoken"
            data = self._make_request(url, {
                "appkey": appkey,
                "appsecret": appsecret
            })
            
            token = data["access_token"]
            logger.debug(f"Successfully obtained access token: {token[:4]}***")
            return token
            
        except Exception as e:
            logger.error(f"Failed to get access token: {str(e)}", exc_info=True)
            raise

    def get_department_list(self, fetch_child: bool = True) -> str:
        """获取部门列表"""
        try:
            access_token = self.get_access_token()
            url = f"{self.base_url}/v1/department/list"
            data = self._make_request(url, {
                "access_token": access_token,
                "fetch_child": fetch_child
            })
            
            departments = data.get("department", [])
            result = []
            for dept in departments:
                result.append(
                    f"Department ID: {dept['id']}\n"
                    f"Name: {dept['name']}\n"
                    f"Parent ID: {dept.get('parentid', 'N/A')}\n"
                    f"---"
                )
            return "\n".join(result) if result else "No departments found"
            
        except Exception as e:
            logger.error(f"Failed to get department list: {str(e)}")
            return f"Error: {str(e)}"

    def get_department_users(self, department_id: int) -> str:
        """获取部门用户列表"""
        try:
            access_token = self.get_access_token()
            url = f"{self.base_url}/v1/user/simplelist"
            data = self._make_request(url, {
                "access_token": access_token,
                "department_id": department_id
            })
            
            users = data.get("userlist", [])
            result = []
            for user in users:
                result.append(
                    f"User ID: {user['userid']}\n"
                    f"Name: {user['name']}\n"
                    f"---"
                )
            return "\n".join(result) if result else "No users found in this department"
            
        except Exception as e:
            logger.error(f"Failed to get department users: {str(e)}")
            return f"Error: {str(e)}"

    def get_user_detail(self, userid: str) -> Dict[str, Any]:
        """获取用户详细信息"""
        try:
            access_token = self.get_access_token()
            url = f"{self.base_url}/v1/user/get"
            return self._make_request(url, {
                "access_token": access_token,
                "userid": userid
            })
        except Exception as e:
            logger.error(f"Failed to get user details: {str(e)}")
            raise

    def search_user_by_name(self, name: str) -> str:
        """根据姓名搜索用户信息"""
        try:
            # 获取所有部门
            dept_list_str = self.get_department_list()
            if not dept_list_str or "Error" in dept_list_str:
                return f"Failed to get department list: {dept_list_str}"
            
            # 解析部门列表字符串
            departments = []
            current_dept = {}
            for line in dept_list_str.split('\n'):
                if line.startswith('Department ID:'):
                    if current_dept:
                        departments.append(current_dept)
                    current_dept = {'id': int(line.split(': ')[1])}
                elif line.startswith('Name:'):
                    current_dept['name'] = line.split(': ')[1]
            if current_dept:
                departments.append(current_dept)
            
            # 遍历所有部门查找用户
            for dept in departments:
                dept_id = dept['id']
                users_str = self.get_department_users(dept_id)
                
                if "Error" in users_str or "Failed" in users_str:
                    logger.warning(f"Failed to get users for department {dept_id}: {users_str}")
                    continue
                
                # 解析用户列表字符串
                users = []
                current_user = {}
                for line in users_str.split('\n'):
                    if line.startswith('User ID:'):
                        if current_user:
                            users.append(current_user)
                        current_user = {'userid': line.split(': ')[1]}
                    elif line.startswith('Name:'):
                        current_user['name'] = line.split(': ')[1]
                if current_user:
                    users.append(current_user)
                
                # 在部门中查找匹配姓名的用户
                for user in users:
                    if user['name'] == name:
                        try:
                            # 获取用户详细信息
                            user_detail = self.get_user_detail(user['userid'])
                            return (f"Found user:\n"
                                   f"User ID: {user_detail['userid']}\n"
                                   f"Name: {user_detail['name']}\n"
                                   f"Mobile: {user_detail.get('mobile', 'N/A')}\n"
                                   f"Email: {user_detail.get('email', 'N/A')}\n"
                                   f"Position: {user_detail.get('position', 'N/A')}\n"
                                   f"Department: {dept['name']}")
                        except Exception as e:
                            logger.error(f"Failed to get details for user {user['userid']}: {str(e)}")
                            continue
            
            return f"No user found with name: {name}"
            
        except Exception as e:
            logger.error(f"Error searching for user: {str(e)}")
            return f"Error: {str(e)}"

    def setup_tools(self):
        logger.debug("Setting up MCP tools...")
        
        tools = [
            Tool(
                name="get_access_token",
                description="Retrieves an access token from the DingTalk API for authentication purposes.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            ),
            Tool(
                name="get_department_list",
                description="Retrieves a list of all departments in the organization.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "fetch_child": {
                            "type": "boolean",
                            "description": "Whether to include child departments in the response. Default is true.",
                            "default": True
                        }
                    },
                    "required": []
                }
            ),
            Tool(
                name="get_department_users",
                description="Retrieves a list of users in a specific department.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "department_id": {
                            "type": "integer",
                            "description": "The ID of the department to query."
                        }
                    },
                    "required": ["department_id"]
                }
            ),
            Tool(
                name="search_user_by_name",
                description="Searches for a user across all departments by their name.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "The exact name of the user to search for."
                        }
                    },
                    "required": ["name"]
                }
            )
        ]
        
        async def list_tools() -> List[Tool]:
            logger.debug("list_tools called")
            return tools
        
        async def call_tool(name: str, arguments: dict) -> List[TextContent]:
            logger.debug(f"Tool called: {name} with arguments: {arguments}")
            try:
                result = None
                if name == "get_access_token":
                    token = self.get_access_token()
                    result = [TextContent(type="text", text=f"Access Token: {token}")]
                
                elif name == "get_department_list":
                    fetch_child = arguments.get("fetch_child", True)
                    logger.debug(f"Fetching department list with fetch_child={fetch_child}")
                    result = self.get_department_list(fetch_child)
                    result = [TextContent(type="text", text=result)]
                
                elif name == "get_department_users":
                    department_id = arguments["department_id"]
                    logger.debug(f"Fetching users for department ID: {department_id}")
                    result = self.get_department_users(department_id)
                    result = [TextContent(type="text", text=result)]
                
                elif name == "search_user_by_name":
                    name = arguments["name"]
                    logger.debug(f"Searching for user with name: {name}")
                    result = self.search_user_by_name(name)
                    result = [TextContent(type="text", text=result)]
                
                else:
                    logger.warning(f"Unknown tool called: {name}")
                    result = [TextContent(type="text", text=f"Unknown tool: {name}")]
                
                logger.debug(f"Tool {name} completed with result: {result}")
                return result
                    
            except Exception as e:
                logger.error(f"Error executing tool {name}: {str(e)}", exc_info=True)
                return [TextContent(type="text", text=f"Error: {str(e)}")]
        
        self.app.list_tools_handler = list_tools
        self.app.call_tool_handler = call_tool

    def setup_prompts(self):
        """设置 Prompts 处理器"""
        logger.debug("Setting up MCP prompts...")
        
        async def list_prompts() -> List[Prompt]:
            logger.debug("list_prompts called")
            return []
        
        async def get_prompt(name: str, arguments: Optional[Dict[str, str]] = None) -> GetPromptResult:
            logger.debug(f"get_prompt called with name: {name}, arguments: {arguments}")
            return GetPromptResult(
                description="DingTalk MCP Prompt",
                messages=[
                    PromptMessage(
                        role="system",
                        content=TextContent(
                            type="text",
                            text="This is a DingTalk MCP service."
                        )
                    )
                ]
            )
        
        self.app.list_prompts_handler = list_prompts
        self.app.get_prompt_handler = get_prompt

    async def run(self):
        logger.info("Starting Dingding MCP server...")
        
        async with stdio_server() as (read_stream, write_stream):
            logger.info("stdio server started")
            try:
                logger.debug("Initializing server with streams")
                await self.app.run(
                    read_stream,
                    write_stream,
                    InitializationOptions(
                        server_name="dingding-mcp",
                        server_version="0.1.0",
                        capabilities=self.app.get_capabilities()
                    )
                )
            except Exception as e:
                logger.error(f"Server error: {str(e)}", exc_info=True)
                raise
            finally:
                logger.debug("Server run completed")

def main():
    logger.info("Main function started")
    try:
        server = DingdingMCPServer()
        logger.debug("Server instance created")
        asyncio.run(server.run())
    except Exception as e:
        logger.error(f"Main function error: {str(e)}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("Main function completed")

if __name__ == "__main__":
    main() 
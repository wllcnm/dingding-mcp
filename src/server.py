import asyncio
import logging
import os
import sys
from typing import List, Optional, Dict, Any
import requests
from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.stdio import stdio_server

# 日志配置
logging.basicConfig(
    level=logging.INFO,
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
        self.base_url = "https://oapi.dingtalk.com"
        self.access_token = None
        self._session = requests.Session()

    def _make_request(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """发送 HTTP 请求并处理通用错误"""
        try:
            response = self._session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("errcode", 0) != 0:
                raise DingTalkAPIError(
                    "DingTalk API error",
                    data.get("errcode", -1),
                    data.get("errmsg", "Unknown error")
                )
            
            return data
        except requests.RequestException as e:
            logger.error(f"HTTP request failed: {str(e)}")
            raise DingTalkAPIError("HTTP request failed", -1, str(e))
        except ValueError as e:
            logger.error(f"Invalid JSON response: {str(e)}")
            raise DingTalkAPIError("Invalid JSON response", -1, str(e))

    def get_access_token(self) -> str:
        """获取钉钉access token"""
        try:
            appkey = os.environ.get("DINGDING_APP_KEY")
            appsecret = os.environ.get("DINGDING_APP_SECRET")
            
            if not all([appkey, appsecret]):
                raise ValueError("Missing DingTalk API credentials in environment variables")
            
            url = f"{self.base_url}/gettoken"
            data = self._make_request(url, {
                "appkey": appkey,
                "appsecret": appsecret
            })
            
            return data["access_token"]
            
        except Exception as e:
            logger.error(f"Failed to get access token: {str(e)}")
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

async def main():
    logger.info("Starting Dingding MCP server...")
    
    try:
        # 创建服务器实例
        server = DingdingMCPServer()
        logger.info("Dingding MCP server instance created")
        
        # 创建 MCP 服务器
        app = Server("dingding-mcp")
        logger.info("MCP server instance created")
        
        # 注册工具列表
        tools = [
            Tool(
                name="get_access_token",
                description="""Retrieves an access token from the DingTalk API for authentication purposes.
                Use this tool when you need to manually obtain an access token for testing or debugging.
                Note: Most other tools automatically handle token management, so you rarely need to call this directly.
                Returns: A valid access token string if successful, or an error message if failed.""",
                function=server.get_access_token,
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            ),
            Tool(
                name="get_department_list",
                description="""Retrieves a list of all departments in the organization.
                Use this tool when you need to:
                - Get an overview of the organization structure
                - Find department IDs for other API calls
                - Check the hierarchy of departments
                - Verify if a specific department exists
                The response includes department IDs, names, and parent department IDs.
                Set fetch_child=false if you only need top-level departments.""",
                function=server.get_department_list,
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
                description="""Retrieves a list of users in a specific department.
                Use this tool when you need to:
                - Get all members of a particular department
                - Check if a user belongs to a department
                - Find user IDs within a department
                - List available users for task assignment
                Requires a valid department ID (can be obtained from get_department_list).
                Returns basic user information including user ID and name.""",
                function=server.get_department_users,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "department_id": {
                            "type": "integer",
                            "description": "The ID of the department to query. Must be a valid department ID from get_department_list."
                        }
                    },
                    "required": ["department_id"]
                }
            ),
            Tool(
                name="search_user_by_name",
                description="""Searches for a user across all departments by their name.
                Use this tool when you need to:
                - Find detailed information about a specific user
                - Verify if a user exists in the organization
                - Get contact information for a user
                - Check which department a user belongs to
                This tool will search through all departments to find the user.
                Returns comprehensive user details including:
                - User ID and name
                - Contact information (mobile and email)
                - Position and department
                Note: This operation may take longer as it searches through all departments.""",
                function=server.search_user_by_name,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "The exact name of the user to search for. Must match the user's name in DingTalk exactly."
                        }
                    },
                    "required": ["name"]
                }
            )
        ]
        
        # 设置工具列表
        app.tools = tools
        logger.info("Tools registered")
        
        async with stdio_server() as (read_stream, write_stream):
            logger.info("stdio server started")
            try:
                await app.run(
                    read_stream,
                    write_stream,
                    app.create_initialization_options()
                )
            except Exception as e:
                logger.error(f"Server run error: {str(e)}", exc_info=True)
                raise
    except Exception as e:
        logger.error(f"Server initialization error: {str(e)}", exc_info=True)
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Main execution error: {str(e)}", exc_info=True)
        sys.exit(1) 
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库备份通知模块
支持邮件通知和企业微信通知
"""

import os
import sys
import json
import smtplib
import argparse
import logging
import hashlib
import time
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from urllib.parse import urlencode

# 配置日志
logger = logging.getLogger(__name__)

# 尝试导入 requests，如果失败则提示安装
try:
    import requests
except ImportError:
    print("错误: 需要安装 requests 库")
    print("请运行: pip3 install requests")
    sys.exit(1)


# 配置文件路径（已废弃，保留用于向后兼容）
TOKEN_CACHE_FILE = "/tmp/wechat_token_cache.json"
TOKEN_CACHE_DURATION = 7200  # token 缓存2小时（企业微信 token 有效期）


class EmailNotifier:
    """邮件通知器"""

    def __init__(self, config):
        """
        初始化邮件通知器

        Args:
            config: 邮件配置字典
        """
        self.config = config
        self.smtp_server = config.get('smtp_server', '')
        self.smtp_port = int(config.get('smtp_port', 587))
        self.use_tls = config.get('use_tls', True)
        self.username = config.get('username', '')
        self.password = config.get('password', '')
        self.from_address = config.get('from_address', self.username)
        self.recipients = config.get('recipients', [])

        if not self.recipients:
            raise ValueError("未配置邮件收件人")

    def send(self, subject, content, is_html=False):
        """
        发送邮件

        Args:
            subject: 邮件主题
            content: 邮件内容
            is_html: 是否为HTML格式

        Returns:
            bool: 发送成功返回 True，否则返回 False
        """
        if not self.recipients:
            print("警告: 没有配置邮件收件人，跳过发送")
            return False

        try:
            # 创建邮件消息
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = formataddr(('数据库备份系统', self.from_address))
            msg['To'] = ', '.join(self.recipients)

            # 添加邮件内容
            if is_html:
                msg.attach(MIMEText(content, 'html', 'utf-8'))
            else:
                msg.attach(MIMEText(content, 'plain', 'utf-8'))

            # 连接 SMTP 服务器
            if self.use_tls:
                # 使用 TLS (通常是 587 端口)
                server = smtplib.SMTP(self.smtp_server, self.smtp_port)
                server.starttls()
            else:
                # 使用 SSL (通常是 465 端口) 或无加密
                if self.smtp_port == 465:
                    server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port)
                else:
                    server = smtplib.SMTP(self.smtp_server, self.smtp_port)

            # 登录
            if self.username and self.password:
                server.login(self.username, self.password)

            # 发送邮件
            server.sendmail(self.from_address, self.recipients, msg.as_string())
            server.quit()

            print(f"邮件通知已发送到 {', '.join(self.recipients)}")
            return True

        except Exception as e:
            print(f"发送邮件失败: {str(e)}")
            return False


class WeChatNotifier:
    """企业微信应用消息通知器"""

    def __init__(self, config):
        """
        初始化企业微信通知器

        Args:
            config: 企业微信配置字典
        """
        self.config = config
        self.corp_id = config.get('corp_id', '')
        self.corp_secret = config.get('corp_secret', '')
        self.agent_id = int(config.get('agent_id', 0))
        self.to_users = config.get('to_users', '@all')

        if not self.corp_id or not self.corp_secret or not self.agent_id:
            raise ValueError("企业微信配置不完整")

        # 生成配置的唯一标识，用于判断配置是否变化
        self.config_key = hashlib.md5(f"{self.corp_id}_{self.corp_secret}".encode()).hexdigest()

    def _get_access_token(self):
        """
        获取企业微信 access_token

        Returns:
            str: access_token
        """
        # 检查缓存
        if os.path.exists(TOKEN_CACHE_FILE):
            try:
                with open(TOKEN_CACHE_FILE, 'r') as f:
                    cache_data = json.load(f)
                    cache_time = cache_data.get('time', 0)
                    cache_key = cache_data.get('config_key', '')

                    # 检查配置是否变化
                    if cache_key != self.config_key:
                        logger.info("[企业微信] 配置已变化，清除旧缓存")
                        self._clear_token_cache()
                    elif time.time() - cache_time < TOKEN_CACHE_DURATION:
                        return cache_data.get('access_token', '')
            except (json.JSONDecodeError, IOError):
                pass

        # 从 API 获取新 token
        url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        params = {
            'corpid': self.corp_id,
            'corpsecret': self.corp_secret
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get('errcode', -1) != 0:
                raise Exception(f"获取 access_token 失败: {data.get('errmsg', '未知错误')}")

            access_token = data.get('access_token', '')

            # 缓存 token，同时保存配置 key
            try:
                with open(TOKEN_CACHE_FILE, 'w') as f:
                    json.dump({
                        'access_token': access_token,
                        'time': time.time(),
                        'config_key': self.config_key
                    }, f)
            except IOError:
                pass  # 缓存失败不影响继续

            return access_token

        except Exception as e:
            print(f"获取企业微信 access_token 失败: {str(e)}")
            raise

    def _clear_token_cache(self):
        """清除 token 缓存"""
        try:
            if os.path.exists(TOKEN_CACHE_FILE):
                os.remove(TOKEN_CACHE_FILE)
                logger.info("[企业微信] 已清除 token 缓存")
        except Exception as e:
            logger.warning(f"[企业微信] 清除缓存失败: {str(e)}")

    def _clean_markdown(self, text):
        """
        将 markdown 格式转换为纯文本

        Args:
            text: markdown 格式的文本

        Returns:
            str: 纯文本
        """
        # 移除 markdown 语法
        text = text.replace('### ', '')      # 移除三级标题
        text = text.replace('## ', '')       # 移除二级标题
        text = text.replace('# ', '')        # 移除一级标题
        text = text.replace('**', '')        # 移除加粗
        text = text.replace('*', '')         # 移除斜体
        text = text.replace('`', '')         # 移除行内代码
        return text

    def send(self, title, content):
        """
        发送企业微信消息

        Args:
            title: 消息标题
            content: 消息内容

        Returns:
            bool: 发送成功返回 True，否则返回 False
        """
        # 尝试发送，如果 token 失效则重试一次
        for attempt in range(2):
            try:
                logger.info("[企业微信] 开始获取 access_token...")
                access_token = self._get_access_token()
                logger.info(f"[企业微信] 获取到 token: {access_token[:10] if access_token else 'None'}...")

                url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}"

                # 将 markdown 格式转换为纯文本
                title_clean = self._clean_markdown(title)
                content_clean = self._clean_markdown(content)
                message_content = f"{title_clean}\n\n{content_clean}"

                data = {
                    "touser": self.to_users,
                    "msgtype": "text",
                    "agentid": self.agent_id,
                    "text": {
                        "content": message_content
                    },
                    "safe": 0
                }

                logger.info(f"[企业微信] 发送消息到 {self.to_users}, agentid={self.agent_id}")
                logger.debug(f"[企业微信] 消息内容: {message_content}")
                response = requests.post(url, json=data, timeout=10)
                logger.info(f"[企业微信] 响应状态码: {response.status_code}")
                logger.info(f"[企业微信] 响应内容: {response.text}")

                response.raise_for_status()
                result = response.json()

                if result.get('errcode', -1) != 0:
                    errcode = result.get('errcode')
                    errmsg = result.get('errmsg', '未知错误')

                    # token 相关的错误码，清除缓存并重试
                    if errcode in [40014, 42001, 42007, 42009] and attempt == 0:
                        logger.warning(f"[企业微信] Token 失效 (errcode={errcode})，清除缓存并重试...")
                        self._clear_token_cache()
                        continue

                    logger.error(f"[企业微信] 消息发送失败: errcode={errcode}, errmsg={errmsg}")
                    return False

                logger.info(f"[企业微信] 通知已成功发送到 {self.to_users}")
                return True

            except Exception as e:
                logger.error(f"[企业微信] 发送通知失败: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                return False

        return False


def format_backup_message(db_type, status, message, trigger_type="自动", backup_file=None):
    """
    格式化备份通知消息

    Args:
        db_type: 数据库类型 (PostgreSQL/MySQL)
        status: 备份状态 (成功/失败)
        message: 备份消息
        trigger_type: 触发类型 (自动/手动)
        backup_file: 备份文件名（可选）

    Returns:
        tuple: (title, content)
    """
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if status == "成功":
        title = f"[成功] 数据库备份成功 - {db_type}"

        content = f"""备份类型: {db_type}
时间: {timestamp}
触发方式: {trigger_type}
状态: 成功
详情: {message}"""

        if backup_file:
            content += f"""
备份文件: {backup_file}"""

    else:
        title = f"[失败] 数据库备份失败 - {db_type}"

        content = f"""备份类型: {db_type}
时间: {timestamp}
触发方式: {trigger_type}
状态: 失败
错误信息: {message}"""

    return title, content


def load_config():
    """从数据库加载配置"""
    try:
        # 尝试多个可能的路径
        possible_paths = ['/', '/root/db-backup-agent', '/app']
        for path in possible_paths:
            if os.path.exists(os.path.join(path, 'config_manager.py')):
                sys.path.insert(0, path)
                from config_manager import get_notification_config
                config = get_notification_config()
                return {'notifications': config}
        raise Exception("找不到 config_manager.py")
    except Exception as e:
        print(f"从数据库加载通知配置失败: {str(e)}")
        return {}


def send_backup_notification(db_type, status, message, trigger_type="自动", backup_file=None):
    """
    发送备份通知

    Args:
        db_type: 数据库类型 (PostgreSQL/MySQL)
        status: 备份状态 (成功/失败)
        message: 备份消息
        trigger_type: 触发类型 (自动/手动)
        backup_file: 备份文件名（可选）

    Returns:
        bool: 至少有一个通知发送成功返回 True
    """
    config = load_config()
    notifications_config = config.get('notifications', {})

    # 检查通知是否启用
    if not notifications_config.get('enabled', False):
        print("通知功能未启用")
        return False

    # 检查是否在当前状态下发送通知
    if status == "成功" and not notifications_config.get('on_success', True):
        print("配置为成功时不发送通知")
        return False

    if status == "失败" and not notifications_config.get('on_failure', True):
        print("配置为失败时不发送通知")
        return False

    # 格式化消息
    title, content = format_backup_message(db_type, status, message, trigger_type, backup_file)

    success_count = 0

    # 发送邮件通知
    email_config = notifications_config.get('email', {})
    if email_config.get('enabled', False):
        try:
            email_notifier = EmailNotifier(email_config)
            if email_notifier.send(title, content, is_html=False):
                success_count += 1
        except Exception as e:
            print(f"邮件通知发送失败: {str(e)}")

    # 发送企业微信通知
    wechat_config = notifications_config.get('wechat', {})
    if wechat_config.get('enabled', False):
        try:
            print(f"开始发送企业微信通知...")
            wechat_notifier = WeChatNotifier(wechat_config)
            if wechat_notifier.send(title, content):
                print(f"企业微信通知发送成功")
                success_count += 1
            else:
                print(f"企业微信通知发送失败（send方法返回False）")
        except Exception as e:
            print(f"企业微信通知发送失败: {str(e)}")
            import traceback
            traceback.print_exc()

    return success_count > 0


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description='数据库备份通知工具')
    parser.add_argument('--type', required=True, help='数据库类型 (PostgreSQL/MySQL)')
    parser.add_argument('--status', required=True, choices=['成功', '失败'], help='备份状态')
    parser.add_argument('--message', required=True, help='备份消息')
    parser.add_argument('--trigger', default='自动', help='触发类型 (自动/手动)')
    parser.add_argument('--file', help='备份文件名（可选）')

    args = parser.parse_args()

    # 发送通知
    success = send_backup_notification(
        db_type=args.type,
        status=args.status,
        message=args.message,
        trigger_type=args.trigger,
        backup_file=args.file
    )

    if success:
        print("通知发送成功")
        sys.exit(0)
    else:
        print("通知发送失败")
        sys.exit(1)


if __name__ == '__main__':
    main()

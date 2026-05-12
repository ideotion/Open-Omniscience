"""
Pillar 4: Real-Time Monitoring & Alerting System - Notification Channels

Manages multiple notification channels for alerts.
"""

import asyncio
import smtplib
import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable, Union
from enum import Enum
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import aiohttp


class NotificationChannelType(Enum):
    EMAIL = "email"
    WEBHOOK = "webhook"
    SLACK = "slack"
    DISCORD = "discord"
    TELEGRAM = "telegram"
    SMS = "sms"
    CUSTOM = "custom"


class NotificationStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"


@dataclass
class NotificationResult:
    """Result of a notification attempt."""
    channel: str
    channel_type: NotificationChannelType
    status: NotificationStatus
    message: str
    timestamp: float = field(default_factory=lambda: __import__('time').time())
    error: Optional[str] = None


@dataclass
class NotificationChannelConfig:
    """Configuration for a notification channel."""
    id: str
    name: str
    channel_type: NotificationChannelType
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)  # Alert tags to notify on
    min_severity: Optional[str] = None  # Minimum severity to notify on
    rate_limit: int = 10  # Notifications per minute


class NotificationChannelManager:
    """
    Manages multiple notification channels with support for:
    - Email notifications with templating
    - Webhook notifications
    - Slack/Discord/Teams integration
    - SMS notifications (via third-party gateways)
    - Custom notification channels
    """

    def __init__(self):
        """Initialize the notification channel manager."""
        self.channels: Dict[str, NotificationChannelConfig] = {}
        self.rate_limits: Dict[str, List[float]] = {}  # channel_id -> [timestamps]
        self.logger = logging.getLogger("NotificationChannelManager")
        self.session: Optional[aiohttp.ClientSession] = None

    async def initialize(self) -> None:
        """Initialize the notification manager (e.g., create HTTP session)."""
        self.session = aiohttp.ClientSession()

    async def shutdown(self) -> None:
        """Shutdown the notification manager."""
        if self.session:
            await self.session.close()
            self.session = None

    def add_channel(self, config: NotificationChannelConfig) -> None:
        """Add a notification channel."""
        self.channels[config.id] = config
        self.rate_limits[config.id] = []
        self.logger.info(f"Added notification channel: {config.id} ({config.channel_type.value})")

    def remove_channel(self, channel_id: str) -> bool:
        """Remove a notification channel."""
        if channel_id in self.channels:
            del self.channels[channel_id]
            if channel_id in self.rate_limits:
                del self.rate_limits[channel_id]
            self.logger.info(f"Removed notification channel: {channel_id}")
            return True
        return False

    def get_channel(self, channel_id: str) -> Optional[NotificationChannelConfig]:
        """Get a notification channel by ID."""
        return self.channels.get(channel_id)

    def list_channels(self) -> List[NotificationChannelConfig]:
        """List all notification channels."""
        return list(self.channels.values())

    async def send_notification(
        self,
        channel_id: str,
        title: str,
        message: str,
        alert_data: Optional[Dict[str, Any]] = None,
    ) -> NotificationResult:
        """
        Send a notification through a specific channel.

        Args:
            channel_id: ID of the channel to use.
            title: Notification title.
            message: Notification message.
            alert_data: Optional alert data for templating.

        Returns:
            Result of the notification attempt.
        """
        if channel_id not in self.channels:
            return NotificationResult(
                channel=channel_id,
                channel_type=NotificationChannelType.CUSTOM,
                status=NotificationStatus.FAILED,
                message="Channel not found",
                error=f"Channel {channel_id} not found",
            )

        channel = self.channels[channel_id]
        if not channel.enabled:
            return NotificationResult(
                channel=channel_id,
                channel_type=channel.channel_type,
                status=NotificationStatus.FAILED,
                message="Channel disabled",
                error=f"Channel {channel_id} is disabled",
            )

        # Check rate limit
        if not self._can_send(channel_id, channel.rate_limit):
            return NotificationResult(
                channel=channel_id,
                channel_type=channel.channel_type,
                status=NotificationStatus.FAILED,
                message="Rate limited",
                error=f"Rate limit exceeded for channel {channel_id}",
            )

        try:
            # Format message with alert data if provided
            formatted_message = self._format_message(message, alert_data or {})

            # Send based on channel type
            if channel.channel_type == NotificationChannelType.EMAIL:
                result = await self._send_email(channel, title, formatted_message)
            elif channel.channel_type == NotificationChannelType.WEBHOOK:
                result = await self._send_webhook(channel, title, formatted_message, alert_data)
            elif channel.channel_type == NotificationChannelType.SLACK:
                result = await self._send_slack(channel, title, formatted_message)
            elif channel.channel_type == NotificationChannelType.DISCORD:
                result = await self._send_discord(channel, title, formatted_message)
            elif channel.channel_type == NotificationChannelType.TELEGRAM:
                result = await self._send_telegram(channel, title, formatted_message)
            elif channel.channel_type == NotificationChannelType.SMS:
                result = await self._send_sms(channel, title, formatted_message)
            else:  # CUSTOM
                result = await self._send_custom(channel, title, formatted_message, alert_data)

            # Record successful send
            self._record_send(channel_id)

            return result

        except Exception as e:
            self.logger.error(f"Error sending notification to channel {channel_id}: {e}")
            return NotificationResult(
                channel=channel_id,
                channel_type=channel.channel_type,
                status=NotificationStatus.FAILED,
                message=f"Notification failed: {str(e)}",
                error=str(e),
            )

    async def broadcast_notification(
        self,
        title: str,
        message: str,
        alert_data: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        min_severity: Optional[str] = None,
    ) -> List[NotificationResult]:
        """
        Send a notification to all matching channels.

        Args:
            title: Notification title.
            message: Notification message.
            alert_data: Optional alert data for templating.
            tags: Only send to channels matching these tags.
            min_severity: Only send to channels with this minimum severity.

        Returns:
            List of notification results.
        """
        results = []
        tasks = []

        for channel_id, channel in self.channels.items():
            if not channel.enabled:
                continue

            # Check tag match
            if tags:
                if not any(tag in channel.tags for tag in tags):
                    continue

            # Check severity match
            if min_severity and channel.min_severity:
                severity_order = ["info", "low", "medium", "high", "critical"]
                if severity_order.index(min_severity.lower()) > severity_order.index(channel.min_severity.lower()):
                    continue

            tasks.append(self.send_notification(channel_id, title, message, alert_data))

        # Send notifications concurrently with rate limiting
        for i, task in enumerate(tasks):
            if i > 0 and i % 5 == 0:  # Limit to 5 concurrent sends
                batch_results = await asyncio.gather(*tasks[:5])
                results.extend(batch_results)
                tasks = tasks[5:]
                await asyncio.sleep(0.1)  # Small delay between batches

        if tasks:
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)

        return results

    def _can_send(self, channel_id: str, rate_limit: int) -> bool:
        """Check if a channel can send a notification (respects rate limits)."""
        now = __import__('time').time()

        # Clean up old timestamps
        if channel_id in self.rate_limits:
            self.rate_limits[channel_id] = [
                ts for ts in self.rate_limits[channel_id]
                if now - ts < 60.0  # Keep only last minute
            ]

            if len(self.rate_limits[channel_id]) >= rate_limit:
                oldest = min(self.rate_limits[channel_id])
                if now - oldest < 60.0:
                    return False

        return True

    def _record_send(self, channel_id: str) -> None:
        """Record a notification send for rate limiting."""
        if channel_id in self.rate_limits:
            self.rate_limits[channel_id].append(__import__('time').time())

    def _format_message(self, template: str, data: Dict[str, Any]) -> str:
        """
        Format a message template with data.

        Args:
            template: Message template with {placeholders}.
            data: Data to use for formatting.

        Returns:
            Formatted message.
        """
        try:
            return template.format(**data)
        except Exception:
            return template  # Return original if formatting fails

    async def _send_email(
        self,
        channel: NotificationChannelConfig,
        title: str,
        message: str,
    ) -> NotificationResult:
        """Send an email notification."""
        config = channel.config

        # Get email configuration
        smtp_host = config.get("smtp_host", "localhost")
        smtp_port = config.get("smtp_port", 587)
        smtp_user = config.get("smtp_user", "")
        smtp_password = config.get("smtp_password", "")
        smtp_use_tls = config.get("smtp_use_tls", True)
        from_addr = config.get("from_addr", "open-omniscience@localhost")
        to_addrs = config.get("to_addrs", [])

        if not to_addrs:
            return NotificationResult(
                channel=channel.id,
                channel_type=NotificationChannelType.EMAIL,
                status=NotificationStatus.FAILED,
                message="No recipients configured",
                error="No recipients configured for email channel",
            )

        # Create email message
        msg = MIMEMultipart()
        msg["From"] = from_addr
        msg["To"] = ", ".join(to_addrs)
        msg["Subject"] = title
        msg.attach(MIMEText(message, "plain"))

        try:
            # Send email
            if smtp_use_tls:
                server = smtplib.SMTP(smtp_host, smtp_port)
                server.starttls()
                if smtp_user and smtp_password:
                    server.login(smtp_user, smtp_password)
                server.sendmail(from_addr, to_addrs, msg.as_string())
                server.quit()
            else:
                server = smtplib.SMTP(smtp_host, smtp_port)
                if smtp_user and smtp_password:
                    server.login(smtp_user, smtp_password)
                server.sendmail(from_addr, to_addrs, msg.as_string())
                server.quit()

            return NotificationResult(
                channel=channel.id,
                channel_type=NotificationChannelType.EMAIL,
                status=NotificationStatus.SUCCESS,
                message=f"Email sent to {len(to_addrs)} recipients",
            )

        except Exception as e:
            return NotificationResult(
                channel=channel.id,
                channel_type=NotificationChannelType.EMAIL,
                status=NotificationStatus.FAILED,
                message="Failed to send email",
                error=str(e),
            )

    async def _send_webhook(
        self,
        channel: NotificationChannelConfig,
        title: str,
        message: str,
        alert_data: Optional[Dict[str, Any]] = None,
    ) -> NotificationResult:
        """Send a webhook notification."""
        config = channel.config
        url = config.get("url", "")

        if not url:
            return NotificationResult(
                channel=channel.id,
                channel_type=NotificationChannelType.WEBHOOK,
                status=NotificationStatus.FAILED,
                message="No webhook URL configured",
                error="No webhook URL configured",
            )

        payload = {
            "title": title,
            "message": message,
            "timestamp": __import__('time').time(),
        }

        if alert_data:
            payload["alert"] = alert_data

        headers = {"Content-Type": "application/json"}
        if "headers" in config:
            headers.update(config["headers"])

        try:
            if not self.session:
                self.session = aiohttp.ClientSession()

            async with self.session.post(url, json=payload, headers=headers) as response:
                if response.status >= 200 and response.status < 300:
                    return NotificationResult(
                        channel=channel.id,
                        channel_type=NotificationChannelType.WEBHOOK,
                        status=NotificationStatus.SUCCESS,
                        message=f"Webhook sent to {url}",
                    )
                else:
                    error_text = await response.text()
                    return NotificationResult(
                        channel=channel.id,
                        channel_type=NotificationChannelType.WEBHOOK,
                        status=NotificationStatus.FAILED,
                        message=f"Webhook failed with status {response.status}",
                        error=f"{response.status}: {error_text}",
                    )

        except Exception as e:
            return NotificationResult(
                channel=channel.id,
                channel_type=NotificationChannelType.WEBHOOK,
                status=NotificationStatus.FAILED,
                message="Failed to send webhook",
                error=str(e),
            )

    async def _send_slack(
        self,
        channel: NotificationChannelConfig,
        title: str,
        message: str,
    ) -> NotificationResult:
        """Send a Slack notification."""
        config = channel.config
        webhook_url = config.get("webhook_url", "")

        if not webhook_url:
            return NotificationResult(
                channel=channel.id,
                channel_type=NotificationChannelType.SLACK,
                status=NotificationStatus.FAILED,
                message="No Slack webhook URL configured",
                error="No Slack webhook URL configured",
            )

        # Format Slack message
        slack_message = {
            "text": f"*{title}*\n{message}",
            "username": config.get("username", "OpenOmniscience"),
            "icon_emoji": config.get("icon_emoji", ":robot_face:"),
        }

        try:
            if not self.session:
                self.session = aiohttp.ClientSession()

            async with self.session.post(webhook_url, json=slack_message) as response:
                if response.status == 200:
                    return NotificationResult(
                        channel=channel.id,
                        channel_type=NotificationChannelType.SLACK,
                        status=NotificationStatus.SUCCESS,
                        message="Slack notification sent",
                    )
                else:
                    error_text = await response.text()
                    return NotificationResult(
                        channel=channel.id,
                        channel_type=NotificationChannelType.SLACK,
                        status=NotificationStatus.FAILED,
                        message=f"Slack notification failed with status {response.status}",
                        error=f"{response.status}: {error_text}",
                    )

        except Exception as e:
            return NotificationResult(
                channel=channel.id,
                channel_type=NotificationChannelType.SLACK,
                status=NotificationStatus.FAILED,
                message="Failed to send Slack notification",
                error=str(e),
            )

    async def _send_discord(
        self,
        channel: NotificationChannelConfig,
        title: str,
        message: str,
    ) -> NotificationResult:
        """Send a Discord notification."""
        config = channel.config
        webhook_url = config.get("webhook_url", "")

        if not webhook_url:
            return NotificationResult(
                channel=channel.id,
                channel_type=NotificationChannelType.DISCORD,
                status=NotificationStatus.FAILED,
                message="No Discord webhook URL configured",
                error="No Discord webhook URL configured",
            )

        # Format Discord message
        discord_message = {
            "content": f"**{title}**\n{message}",
            "username": config.get("username", "OpenOmniscience"),
            "avatar_url": config.get("avatar_url", ""),
        }

        try:
            if not self.session:
                self.session = aiohttp.ClientSession()

            async with self.session.post(webhook_url, json=discord_message) as response:
                if response.status == 204:  # Discord returns 204 No Content on success
                    return NotificationResult(
                        channel=channel.id,
                        channel_type=NotificationChannelType.DISCORD,
                        status=NotificationStatus.SUCCESS,
                        message="Discord notification sent",
                    )
                else:
                    error_text = await response.text()
                    return NotificationResult(
                        channel=channel.id,
                        channel_type=NotificationChannelType.DISCORD,
                        status=NotificationStatus.FAILED,
                        message=f"Discord notification failed with status {response.status}",
                        error=f"{response.status}: {error_text}",
                    )

        except Exception as e:
            return NotificationResult(
                channel=channel.id,
                channel_type=NotificationChannelType.DISCORD,
                status=NotificationStatus.FAILED,
                message="Failed to send Discord notification",
                error=str(e),
            )

    async def _send_telegram(
        self,
        channel: NotificationChannelConfig,
        title: str,
        message: str,
    ) -> NotificationResult:
        """Send a Telegram notification."""
        config = channel.config
        bot_token = config.get("bot_token", "")
        chat_id = config.get("chat_id", "")

        if not bot_token or not chat_id:
            return NotificationResult(
                channel=channel.id,
                channel_type=NotificationChannelType.TELEGRAM,
                status=NotificationStatus.FAILED,
                message="Telegram bot token or chat ID not configured",
                error="Telegram bot token or chat ID not configured",
            )

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": f"*{title}*\n{message}",
            "parse_mode": "Markdown",
        }

        try:
            if not self.session:
                self.session = aiohttp.ClientSession()

            async with self.session.post(url, json=payload) as response:
                if response.status == 200:
                    return NotificationResult(
                        channel=channel.id,
                        channel_type=NotificationChannelType.TELEGRAM,
                        status=NotificationStatus.SUCCESS,
                        message="Telegram notification sent",
                    )
                else:
                    error_text = await response.text()
                    return NotificationResult(
                        channel=channel.id,
                        channel_type=NotificationChannelType.TELEGRAM,
                        status=NotificationStatus.FAILED,
                        message=f"Telegram notification failed with status {response.status}",
                        error=f"{response.status}: {error_text}",
                    )

        except Exception as e:
            return NotificationResult(
                channel=channel.id,
                channel_type=NotificationChannelType.TELEGRAM,
                status=NotificationStatus.FAILED,
                message="Failed to send Telegram notification",
                error=str(e),
            )

    async def _send_sms(
        self,
        channel: NotificationChannelConfig,
        title: str,
        message: str,
    ) -> NotificationResult:
        """Send an SMS notification via a third-party gateway."""
        config = channel.config
        gateway = config.get("gateway", "")

        if not gateway:
            return NotificationResult(
                channel=channel.id,
                channel_type=NotificationChannelType.SMS,
                status=NotificationStatus.FAILED,
                message="No SMS gateway configured",
                error="No SMS gateway configured",
            )

        # Placeholder: implement actual SMS sending based on gateway
        # Different gateways have different APIs (Twilio, Nexmo, etc.)
        self.logger.warning(f"SMS sending not implemented for gateway: {gateway}")

        return NotificationResult(
            channel=channel.id,
            channel_type=NotificationChannelType.SMS,
            status=NotificationStatus.FAILED,
            message="SMS sending not implemented",
            error=f"SMS gateway {gateway} not implemented",
        )

    async def _send_custom(
        self,
        channel: NotificationChannelConfig,
        title: str,
        message: str,
        alert_data: Optional[Dict[str, Any]] = None,
    ) -> NotificationResult:
        """Send a notification through a custom channel."""
        config = channel.config
        callback = config.get("callback")

        if not callback or not callable(callback):
            return NotificationResult(
                channel=channel.id,
                channel_type=NotificationChannelType.CUSTOM,
                status=NotificationStatus.FAILED,
                message="No callback configured for custom channel",
                error="No callback configured",
            )

        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(title=title, message=message, alert_data=alert_data)
            else:
                callback(title=title, message=message, alert_data=alert_data)

            return NotificationResult(
                channel=channel.id,
                channel_type=NotificationChannelType.CUSTOM,
                status=NotificationStatus.SUCCESS,
                message="Custom notification sent",
            )

        except Exception as e:
            return NotificationResult(
                channel=channel.id,
                channel_type=NotificationChannelType.CUSTOM,
                status=NotificationStatus.FAILED,
                message="Custom notification failed",
                error=str(e),
            )

    def get_stats(self) -> Dict[str, Any]:
        """Get notification manager statistics."""
        return {
            "total_channels": len(self.channels),
            "enabled_channels": sum(1 for c in self.channels.values() if c.enabled),
            "by_type": {
                t.value: sum(1 for c in self.channels.values() if c.channel_type == t)
                for t in NotificationChannelType
            },
        }

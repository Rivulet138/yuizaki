"""后端多语言支持 - 国际化管理"""

import json
from pathlib import Path
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class I18nManager:
    """国际化管理器"""

    def __init__(self, locales_dir: str = "./locales"):
        """初始化 i18n 管理器

        Args:
            locales_dir: 语言文件目录
        """
        self.locales_dir = Path(locales_dir)
        self.messages: Dict[str, Dict[str, Any]] = {}
        self.current_locale = "zh-CN"
        self.supported_locales = ["zh-CN", "en-US", "ja-JP"]
        self._load_locales()

    def _load_locales(self):
        """加载所有语言文件"""
        for locale in self.supported_locales:
            locale_file = self.locales_dir / f"{locale}.json"
            if locale_file.exists():
                try:
                    with open(locale_file, 'r', encoding='utf-8') as f:
                        self.messages[locale] = json.load(f)
                    logger.info(f"Loaded locale: {locale}")
                except Exception as e:
                    logger.error(f"Failed to load locale {locale}: {e}")
                    self.messages[locale] = {}
            else:
                logger.warning(f"Locale file not found: {locale_file}")
                self.messages[locale] = {}

    def set_locale(self, locale: str) -> bool:
        """设置当前语言

        Args:
            locale: 语言代码 (zh-CN, en-US, ja-JP)

        Returns:
            是否设置成功
        """
        if locale in self.supported_locales:
            self.current_locale = locale
            logger.info(f"Locale set to: {locale}")
            return True
        else:
            logger.warning(f"Unsupported locale: {locale}")
            return False

    def get(self, key: str, locale: Optional[str] = None, default: str = "") -> str:
        """获取翻译文本

        Args:
            key: 翻译键 (支持点号分隔: "common.save")
            locale: 语言代码 (None 表示使用当前语言)
            default: 默认值

        Returns:
            翻译文本
        """
        locale = locale or self.current_locale
        keys = key.split('.')
        value = self.messages.get(locale, {})

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default

        if isinstance(value, str):
            return value if value else default
        return default

    def get_all(self, locale: Optional[str] = None) -> Dict[str, Any]:
        """获取所有翻译

        Args:
            locale: 语言代码

        Returns:
            翻译字典
        """
        locale = locale or self.current_locale
        return self.messages.get(locale, {})

    def get_supported_locales(self) -> list[str]:
        """获取支持的语言列表

        Returns:
            语言代码列表
        """
        return self.supported_locales

    def get_current_locale(self) -> str:
        """获取当前语言

        Returns:
            当前语言代码
        """
        return self.current_locale

    def translate_error(self, error_key: str, locale: Optional[str] = None) -> str:
        """翻译错误消息

        Args:
            error_key: 错误键 (errors.networkError)
            locale: 语言代码

        Returns:
            翻译后的错误消息
        """
        return self.get(error_key, locale, error_key)

    def translate_message(self, message_key: str, locale: Optional[str] = None) -> str:
        """翻译消息

        Args:
            message_key: 消息键
            locale: 语言代码

        Returns:
            翻译后的消息
        """
        return self.get(message_key, locale, message_key)


# 全局 i18n 实例
i18n_manager = I18nManager()


def get_i18n() -> I18nManager:
    """获取全局 i18n 实例"""
    return i18n_manager


def set_locale(locale: str) -> bool:
    """设置全局语言"""
    return i18n_manager.set_locale(locale)


def t(key: str, locale: Optional[str] = None) -> str:
    """翻译快捷函数

    Args:
        key: 翻译键
        locale: 语言代码

    Returns:
        翻译文本
    """
    return i18n_manager.get(key, locale)

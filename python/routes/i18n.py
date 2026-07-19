"""多语言 API 端点"""

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from i18n import get_i18n, set_locale, t
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/i18n", tags=["internationalization"])


@router.get("/locales")
async def get_available_locales():
    """获取可用语言列表"""
    i18n = get_i18n()
    locales = i18n.get_supported_locales()
    return {
        "available": locales,
        "current": i18n.get_current_locale(),
        "localeNames": {
            "zh-CN": "简体中文",
            "en-US": "English",
            "ja-JP": "日本語"
        }
    }


@router.post("/locale")
async def set_current_locale(locale: str = Query(...)):
    """设置当前语言
    
    Args:
        locale: 语言代码 (zh-CN, en-US, ja-JP)
    """
    i18n = get_i18n()
    success = set_locale(locale)
    
    if success:
        logger.info(f"Locale changed to: {locale}")
        return {
            "status": "success",
            "locale": locale,
            "message": t("common.success")
        }
    else:
        logger.warning(f"Failed to set locale: {locale}")
        return JSONResponse(
            {
                "status": "error",
                "locale": i18n.get_current_locale(),
                "message": t("errors.invalidRequest")
            },
            status_code=400,
        )


@router.get("/locale")
async def get_current_locale():
    """获取当前语言"""
    i18n = get_i18n()
    return {
        "locale": i18n.get_current_locale()
    }


@router.get("/messages")
async def get_all_messages(locale: str = Query(None)):
    """获取所有翻译消息
    
    Args:
        locale: 语言代码 (可选，默认使用当前语言)
    """
    i18n = get_i18n()
    messages = i18n.get_all(locale)
    return {
        "locale": locale or i18n.get_current_locale(),
        "messages": messages
    }


@router.get("/message/{key:path}")
async def get_message(key: str, locale: str = Query(None)):
    """获取单个翻译消息
    
    Args:
        key: 翻译键 (支持点号分隔: common.save)
        locale: 语言代码 (可选)
    """
    i18n = get_i18n()
    message = i18n.get(key, locale)
    return {
        "key": key,
        "locale": locale or i18n.get_current_locale(),
        "message": message
    }


@router.get("/error/{error_key:path}")
async def get_error_message(error_key: str, locale: str = Query(None)):
    """获取错误消息翻译
    
    Args:
        error_key: 错误键 (errors.networkError)
        locale: 语言代码 (可选)
    """
    i18n = get_i18n()
    message = i18n.translate_error(error_key, locale)
    return {
        "error": error_key,
        "locale": locale or i18n.get_current_locale(),
        "message": message
    }

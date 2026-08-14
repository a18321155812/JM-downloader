package com.jmcomic.app.api

import org.json.JSONObject

/**
 * 下载配置（与后端 server.py 的配置字段一一对应）
 */
data class DownloadSettings(
    // 基本下载
    val imageThreads: Int = 4,
    val photoThreads: Int = 2,
    val decode: Boolean = true,
    val cache: Boolean = true,
    val rule: String = "Bd_Aauthoroname_Pname",
    val clientType: String = "api",
    val retryTimes: Int = 5,
    val proxy: String = "",
    // PDF
    val pdf: Boolean = false,
    val pdfPassword: String = "",
    val pdfDelete: Boolean = false,
    val pdfRule: String = "{Aid}_{Pname}",
    // ZIP
    val zip: Boolean = false,
    val zipFormat: String = "标准ZIP",
    val zipPassword: String = "",
    val zipLevel: String = "photo",
    val zipDelete: Boolean = false,
    // 封面
    val cover: Boolean = false,
    // 登录
    val login: Boolean = false,
    val username: String = "",
    val password: String = "",
) {
    /** 转成后端 API 需要的 JSON */
    fun toJson(): JSONObject = JSONObject().apply {
        put("image_threads", imageThreads)
        put("photo_threads", photoThreads)
        put("decode", decode)
        put("cache", cache)
        put("rule", rule)
        put("client_type", clientType)
        put("retry_times", retryTimes)
        put("proxy", proxy)
        put("pdf", pdf)
        put("pdf_password", pdfPassword)
        put("pdf_delete", pdfDelete)
        put("pdf_rule", pdfRule)
        put("zip", zip)
        put("zip_format", zipFormat)
        put("zip_password", zipPassword)
        put("zip_level", zipLevel)
        put("zip_delete", zipDelete)
        put("cover", cover)
        put("login", login)
        put("username", username)
        put("password", password)
    }

    companion object {
        fun fromJson(j: JSONObject): DownloadSettings = DownloadSettings(
            imageThreads = j.optInt("image_threads", 4),
            photoThreads = j.optInt("photo_threads", 2),
            decode = j.optBoolean("decode", true),
            cache = j.optBoolean("cache", true),
            rule = j.optString("rule", "Bd_Aauthoroname_Pname"),
            clientType = j.optString("client_type", "api"),
            retryTimes = j.optInt("retry_times", 5),
            proxy = j.optString("proxy", ""),
            pdf = j.optBoolean("pdf", false),
            pdfPassword = j.optString("pdf_password", ""),
            pdfDelete = j.optBoolean("pdf_delete", false),
            pdfRule = j.optString("pdf_rule", "{Aid}_{Pname}"),
            zip = j.optBoolean("zip", false),
            zipFormat = j.optString("zip_format", "标准ZIP"),
            zipPassword = j.optString("zip_password", ""),
            zipLevel = j.optString("zip_level", "photo"),
            zipDelete = j.optBoolean("zip_delete", false),
            cover = j.optBoolean("cover", false),
            login = j.optBoolean("login", false),
            username = j.optString("username", ""),
            password = j.optString("password", ""),
        )

        val RULES = listOf(
            "Bd_Aauthoroname_Pname",
            "Bd_Aidoname_Pname",
        )
        val RULES_LABEL = mapOf(
            "Bd_Aauthoroname_Pname" to "[作者名]/章节名",
            "Bd_Aidoname_Pname" to "[ID名]/章节名",
        )
        // 安卓版不支持 7z（需要 C 库），只提供标准 ZIP 和加密 ZIP
        val ZIP_FORMATS = listOf("标准ZIP", "加密ZIP(AES)")
        val ZIP_LEVELS = listOf("photo", "album")
        val CLIENT_TYPES = listOf("api", "html")
    }
}

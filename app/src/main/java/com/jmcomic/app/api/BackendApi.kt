package com.jmcomic.app.api

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.MediaType.Companion.toMediaType
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * 数据模型
 */
data class AlbumDetail(
    val id: String,
    val title: String,
    val author: String,
    val tags: List<String>,
    val description: String,
    val photoCount: Int,
    val photos: List<PhotoItem>,
)

data class PhotoItem(val id: String, val title: String)

data class TaskInfo(
    val id: String,
    val type: String,
    val status: String,
    val progress: Int,
    val message: String,
)

data class FileInfo(val path: String, val size: Long, val time: Long = 0L)

data class FileListResult(val base: String, val files: List<FileInfo>)

/**
 * 后端 HTTP 客户端（调用电脑上的 jmcomic 后端服务）
 */
class BackendApi(private val baseUrl: String) {

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

    private val jsonMedia = "application/json; charset=utf-8".toMediaType()

    private suspend fun get(path: String): String = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(baseUrl + path).build()
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) throw RuntimeException("HTTP ${resp.code}")
            resp.body?.string() ?: ""
        }
    }

    private suspend fun post(path: String, body: String): String = withContext(Dispatchers.IO) {
        val req = Request.Builder()
            .url(baseUrl + path)
            .post(body.toRequestBody(jsonMedia))
            .build()
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) throw RuntimeException("HTTP ${resp.code}")
            resp.body?.string() ?: ""
        }
    }

    /** 测试后端是否可达 */
    suspend fun ping(): Boolean = withContext(Dispatchers.IO) {
        try {
            val req = Request.Builder().url(baseUrl + "/").build()
            client.newCall(req).execute().use { it.isSuccessful }
        } catch (e: Exception) {
            false
        }
    }

    /** 本子详情 */
    suspend fun getAlbum(id: String): AlbumDetail {
        val json = JSONObject(get("/api/album/$id"))
        val photosArr = json.getJSONArray("photos")
        val photos = buildList {
            for (i in 0 until photosArr.length()) {
                val p = photosArr.getJSONObject(i)
                add(PhotoItem(p.getString("id"), p.getString("title")))
            }
        }
        val tags = buildList {
            val arr = json.optJSONArray("tags") ?: JSONArray()
            for (i in 0 until arr.length()) add(arr.getString(i))
        }
        return AlbumDetail(
            id = json.getString("id"),
            title = json.getString("title"),
            author = json.optString("author", ""),
            tags = tags,
            description = json.optString("description", ""),
            photoCount = json.optInt("photo_count", photos.size),
            photos = photos,
        )
    }

    /** 章节图片总数 */
    suspend fun getPhotoImageCount(photoId: String): Int = withContext(Dispatchers.IO) {
        try {
            JSONObject(get("/api/photo/$photoId")).optInt("image_count", 0)
        } catch (e: Exception) {
            0
        }
    }

    /** 提交下载任务（携带完整配置：PDF/ZIP/封面/登录/并发等） */
    suspend fun submitDownload(id: String, type: String, settings: DownloadSettings): Boolean {
        val body = settings.toJson()
            .put("id", id)
            .put("type", type)
            .toString()
        return try {
            JSONObject(post("/api/download", body)).optBoolean("ok", false)
        } catch (e: Exception) {
            false
        }
    }

    /** 取消任务 */
    suspend fun cancelTask(taskId: String): Boolean = withContext(Dispatchers.IO) {
        try {
            val req = Request.Builder()
                .url("$baseUrl/api/cancel/$taskId")
                .post("{}".toRequestBody(jsonMedia))
                .build()
            client.newCall(req).execute().use { it.isSuccessful }
        } catch (e: Exception) {
            false
        }
    }

    /** 任务列表 */
    suspend fun getTasks(): List<TaskInfo> = withContext(Dispatchers.IO) {
        try {
            val arr = JSONArray(get("/api/tasks"))
            buildList {
                for (i in 0 until arr.length()) {
                    val t = arr.getJSONObject(i)
                    add(
                        TaskInfo(
                            id = t.optString("id", ""),
                            type = t.optString("type", ""),
                            status = t.optString("status", ""),
                            progress = t.optInt("progress", 0),
                            message = t.optString("message", ""),
                        )
                    )
                }
            }
        } catch (e: Exception) {
            emptyList()
        }
    }

    /** 已下载文件列表（含实际下载目录路径） */
    suspend fun getFiles(): FileListResult = withContext(Dispatchers.IO) {
        try {
            val json = JSONObject(get("/api/files"))
            val arr = json.getJSONArray("files")
            val list = buildList {
                for (i in 0 until arr.length()) {
                    val f = arr.getJSONObject(i)
                    add(FileInfo(f.getString("path"), f.optLong("size", 0), f.optLong("time", 0L)))
                }
            }
            FileListResult(json.optString("base", ""), list)
        } catch (e: Exception) {
            FileListResult("", emptyList())
        }
    }

    /** 删除文件或文件夹 */
    suspend fun deletePath(path: String): Boolean = withContext(Dispatchers.IO) {
        try {
            val body = JSONObject().put("path", path).toString()
            val req = Request.Builder()
                .url("$baseUrl/api/delete")
                .post(body.toRequestBody(jsonMedia))
                .build()
            client.newCall(req).execute().use { it.isSuccessful }
        } catch (e: Exception) {
            false
        }
    }

    /** 封面/预览图 URL（供 Coil 加载）；thumb=true 返回缩略图 */
    fun coverUrl(albumId: String): String = "$baseUrl/api/cover/$albumId"
    fun previewUrl(photoId: String, index: Int, thumb: Boolean = false): String =
        "$baseUrl/api/preview/$photoId/$index" + if (thumb) "?size=thumb" else ""

    /** 下载文件 URL */
    fun fileUrl(path: String): String = "$baseUrl/api/file?path=${java.net.URLEncoder.encode(path, "UTF-8")}"
}

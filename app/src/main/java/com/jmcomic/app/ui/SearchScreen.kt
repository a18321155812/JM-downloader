package com.jmcomic.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Download
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Divider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import coil.compose.AsyncImage
import com.jmcomic.app.api.AlbumDetail
import com.jmcomic.app.api.BackendApi
import com.jmcomic.app.api.DownloadSettings
import com.jmcomic.app.api.PhotoItem
import kotlinx.coroutines.launch

/** 解析输入：支持批量（空格/逗号/换行分隔，p 前缀为章节） */
private fun parseIds(text: String): Pair<List<String>, List<String>> {
    val albums = mutableListOf<String>()
    val photos = mutableListOf<String>()
    text.split(Regex("[\\s,，;；]+")).forEach { raw ->
        val s = raw.trim()
        if (s.isEmpty()) return@forEach
        if (s.lowercase().startsWith("p") && s.length > 1 && s.substring(1).all { it.isDigit() }) {
            photos.add(s.substring(1))
        } else if (s.all { it.isDigit() }) {
            albums.add(s)
        }
    }
    return albums to photos
}

@Composable
fun SearchScreen(api: BackendApi, settings: DownloadSettings) {
    // rememberSaveable: 切换页面后保留输入内容
    var idInput by rememberSaveable { mutableStateOf("") }
    var albumList by remember { mutableStateOf<List<AlbumDetail>>(emptyList()) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var previewPhoto by remember { mutableStateOf<PhotoItem?>(null) }
    var previewIndex by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()

    Column(Modifier.fillMaxSize().padding(horizontal = 12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = idInput,
                onValueChange = { idInput = it },
                modifier = Modifier.weight(1f),
                label = { Text("漫画 ID（多个用空格分隔，章节加 p 前缀）") },
                singleLine = true
            )
            Spacer(Modifier.width(8.dp))
            Button(
                onClick = {
                    val (albums, _) = parseIds(idInput)
                    if (albums.isEmpty()) return@Button
                    loading = true
                    error = null
                    scope.launch {
                        val results = mutableListOf<AlbumDetail>()
                        val failed = mutableListOf<String>()
                        for (aid in albums) {
                            try {
                                results.add(api.getAlbum(aid))
                            } catch (e: Exception) {
                                failed.add(aid)
                            }
                        }
                        albumList = results
                        error = if (failed.isNotEmpty() && results.isEmpty()) {
                            "查询失败: ${failed.joinToString(", ")}"
                        } else if (failed.isNotEmpty()) {
                            "部分 ID 查询失败: ${failed.joinToString(", ")}"
                        } else null
                        loading = false
                    }
                }
            ) { Text("查询") }
        }

        // 批量下载按钮
        val (batchAlbums, batchPhotos) = parseIds(idInput)
        if (batchAlbums.isNotEmpty() || batchPhotos.isNotEmpty()) {
            Row(
                Modifier.fillMaxWidth().padding(vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    "识别到 ${batchAlbums.size} 个本子 + ${batchPhotos.size} 个章节",
                    style = MaterialTheme.typography.bodySmall
                )
                Spacer(Modifier.width(8.dp))
                Button(
                    onClick = {
                        scope.launch {
                            batchAlbums.forEach { api.submitDownload(it, "album", settings) }
                            batchPhotos.forEach { api.submitDownload(it, "photo", settings) }
                        }
                    }
                ) { Text("全部下载") }
            }
        }

        when {
            loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }

            error != null -> Text(
                "错误: $error",
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(16.dp)
            )

            albumList.isNotEmpty() -> {
                androidx.compose.foundation.lazy.LazyColumn(Modifier.fillMaxSize()) {
                    items(albumList, key = { it.id }) { album ->
                        AlbumDetailView(
                            album = album,
                            api = api,
                            onPreview = { p -> previewPhoto = p; previewIndex = 0 },
                            onDownload = { id, type ->
                                scope.launch { api.submitDownload(id, type, settings) }
                            }
                        )
                        Divider(Modifier.padding(vertical = 6.dp))
                    }
                }
            }
        }
    }

    previewPhoto?.let { p ->
        PreviewDialog(
            api = api,
            photoId = p.id,
            title = p.title,
            initialIndex = previewIndex,
            onIndexChange = { previewIndex = it },
            onDismiss = { previewPhoto = null }
        )
    }
}

@Composable
fun AlbumDetailView(
    album: AlbumDetail,
    api: BackendApi,
    onPreview: (PhotoItem) -> Unit,
    onDownload: (String, String) -> Unit,
) {
    Column(Modifier.fillMaxWidth()) {
        Row(Modifier.padding(vertical = 8.dp)) {
            AsyncImage(
                model = api.coverUrl(album.id),
                contentDescription = "封面",
                contentScale = ContentScale.Fit,
                modifier = Modifier.size(width = 110.dp, height = 150.dp)
            )
            Column(Modifier.padding(start = 12.dp)) {
                Text(album.title, style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(4.dp))
                Text("作者: ${album.author}", style = MaterialTheme.typography.bodyMedium)
                Spacer(Modifier.height(4.dp))
                Text("章节数: ${album.photoCount}", style = MaterialTheme.typography.bodyMedium)
                Spacer(Modifier.height(4.dp))
                Text(
                    "标签: ${album.tags.joinToString("、")}",
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(Modifier.height(8.dp))
                Button(onClick = { onDownload(album.id, "album") }) {
                    Icon(Icons.Default.Download, null, Modifier.size(16.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("下载整本")
                }
            }
        }
        if (album.description.isNotBlank()) {
            Text(
                album.description,
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(bottom = 8.dp)
            )
        }
        Divider()
        Text("📑 章节列表（点击预览）", style = MaterialTheme.typography.titleSmall,
            modifier = Modifier.padding(vertical = 6.dp))
        album.photos.forEach { photo ->
            Row(
                Modifier.fillMaxWidth()
                    .clickable { onPreview(photo) }
                    .padding(vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(Modifier.weight(1f)) {
                    Text(photo.title, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text("章节 ID: ${photo.id}", style = MaterialTheme.typography.bodySmall)
                }
                OutlinedButton(onClick = { onDownload(photo.id, "photo") }) { Text("下载") }
                Spacer(Modifier.width(8.dp))
                TextButton(onClick = { onPreview(photo) }) { Text("预览") }
            }
            Divider()
        }
    }
}

@Composable
fun PreviewDialog(
    api: BackendApi,
    photoId: String,
    title: String,
    initialIndex: Int,
    onIndexChange: (Int) -> Unit,
    onDismiss: () -> Unit,
) {
    var index by remember { mutableIntStateOf(initialIndex) }
    var total by remember { mutableStateOf(0) }

    // 获取章节图片总数
    LaunchedEffect(photoId) {
        total = api.getPhotoImageCount(photoId)
    }

    Dialog(onDismissRequest = onDismiss) {
        Column(
            Modifier.fillMaxWidth().padding(12.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(title, maxLines = 1, overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.titleSmall)
            Spacer(Modifier.height(8.dp))

            // 大图预览
            var imgError by remember { mutableStateOf<String?>(null) }
            AsyncImage(
                model = api.previewUrl(photoId, index),
                contentDescription = "预览",
                contentScale = ContentScale.Fit,
                onError = { state ->
                    imgError = state.result.throwable?.message ?: "加载失败"
                },
                onSuccess = { imgError = null },
                modifier = Modifier.fillMaxWidth().height(440.dp)
            )
            imgError?.let {
                Text(
                    "图片加载失败: $it",
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.padding(vertical = 4.dp)
                )
            }
            Spacer(Modifier.height(4.dp))

            // 页码
            Text(
                if (total > 0) "第 ${index + 1} / $total 页" else "加载中...",
                style = MaterialTheme.typography.bodySmall
            )
            Spacer(Modifier.height(4.dp))

            // 缩略图条：点击跳转
            LazyRow(
                horizontalArrangement = Arrangement.spacedBy(4.dp),
                modifier = Modifier.fillMaxWidth().height(90.dp)
            ) {
                items(total) { i ->
                    AsyncImage(
                        model = api.previewUrl(photoId, i, thumb = true),
                        contentDescription = "缩略图${i + 1}",
                        contentScale = ContentScale.Crop,
                        modifier = Modifier
                            .width(64.dp)
                            .height(90.dp)
                            .clickable {
                                index = i
                                onIndexChange(i)
                            }
                    )
                }
            }
            Spacer(Modifier.height(4.dp))

            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                TextButton(onClick = {
                    index = (index - 1).coerceAtLeast(0)
                    onIndexChange(index)
                }) { Text("◀ 上一张") }
                TextButton(onClick = {
                    if (total == 0 || index < total - 1) index++
                    onIndexChange(index)
                }) { Text("下一张 ▶") }
            }
            TextButton(onClick = onDismiss) { Text("关闭") }
        }
    }
}

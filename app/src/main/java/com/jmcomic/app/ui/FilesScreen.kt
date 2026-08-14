package com.jmcomic.app.ui

import android.content.Intent
import android.content.pm.ResolveInfo
import android.graphics.drawable.Drawable
import android.net.Uri
import androidx.core.content.FileProvider
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.jmcomic.app.api.BackendApi
import com.jmcomic.app.api.FileInfo
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.Locale

@Composable
fun FilesScreen(api: BackendApi) {
    var fileResult by remember { mutableStateOf<com.jmcomic.app.api.FileListResult?>(null) }
    var loaded by remember { mutableStateOf(false) }
    var refreshKey by remember { mutableIntStateOf(0) }
    // 排序方式：name=名称 size=大小 time=时间；ascending=正序/倒序
    var sortMode by remember { mutableStateOf("name") }
    var ascending by remember { mutableStateOf(true) }
    // 展开的文件夹集合（默认收起）
    var expandedFolders by remember { mutableStateOf(setOf<String>()) }
    // 待删除确认的目标：null=无，Pair(路径, 名称)
    var pendingDelete by remember { mutableStateOf<Pair<String, String>?>(null) }
    // 待选择打开方式：path, mime, 应用列表
    var openTarget by remember {
        mutableStateOf<com.jmcomic.app.api.FileInfo?>(null)
    }
    var openApps by remember { mutableStateOf<List<ResolveInfo>?>(null) }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    // 进入页面 + 点击刷新时重新加载，同时每 5 秒自动刷新一次
    LaunchedEffect(api, refreshKey) {
        while (true) {
            fileResult = api.getFiles()
            loaded = true
            delay(5000)
        }
    }
    val files = fileResult?.files ?: emptyList()

    // 排序（按字段 + 正序/倒序）
    val sortedFiles = remember(files, sortMode, ascending) {
        val sorted = when (sortMode) {
            "name" -> files.sortedBy { it.path.lowercase() }
            "size" -> files.sortedBy { it.size }
            else -> files.sortedBy { it.time }
        }
        if (ascending) sorted else sorted.reversed()
    }
    // 按文件夹分组（path 的第一段）
    val grouped = remember(sortedFiles) {
        sortedFiles.groupBy { it.path.substringBefore('/') }
    }

    Column(Modifier.fillMaxSize().padding(horizontal = 12.dp)) {
        Row(
            Modifier.fillMaxWidth().padding(vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text("📁 已下载文件",
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.weight(1f))
            TextButton(onClick = { refreshKey++ }) { Text("🔄 刷新") }
        }
        val base = fileResult?.base ?: ""
        if (base.isNotEmpty()) {
            Text(
                "下载目录: $base",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.padding(bottom = 4.dp)
            )
        }
        // 排序栏（字段 + 正序/倒序）
        Row(
            Modifier.fillMaxWidth().padding(bottom = 4.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text("排序:", style = MaterialTheme.typography.bodySmall)
            listOf("name" to "名称", "size" to "大小", "time" to "时间").forEach { (mode, label) ->
                TextButton(
                    onClick = { sortMode = mode },
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 8.dp)
                ) {
                    Text(
                        label,
                        style = MaterialTheme.typography.bodySmall,
                        color = if (sortMode == mode) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.onSurface
                    )
                }
            }
            Spacer(Modifier.weight(1f))
            TextButton(
                onClick = { ascending = !ascending },
                contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 8.dp)
            ) {
                Text(
                    if (ascending) "↑ 正序" else "↓ 倒序",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.primary
                )
            }
        }
        if (!loaded) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
        } else if (files.isEmpty()) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("还没有已下载的文件", style = MaterialTheme.typography.bodyMedium)
            }
        } else {
            LazyColumn {
                grouped.forEach { (folder, folderFiles) ->
                    // 文件夹标题行（点击展开/收起，含删除文件夹按钮）
                    val expanded = folder in expandedFolders
                    item(key = "folder_$folder") {
                        Row(
                            Modifier.fillMaxWidth()
                                .clickable {
                                    expandedFolders = if (expanded) expandedFolders - folder
                                    else expandedFolders + folder
                                }
                                .padding(top = 10.dp, bottom = 2.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                if (expanded) "▾" else "▸",
                                style = MaterialTheme.typography.titleSmall,
                                modifier = Modifier.padding(end = 4.dp)
                            )
                            Text(
                                "📂 $folder（${folderFiles.size} 个文件）",
                                style = MaterialTheme.typography.titleSmall,
                                modifier = Modifier.weight(1f)
                            )
                            IconButton(onClick = { pendingDelete = Pair(folder, "文件夹「$folder」（${folderFiles.size} 个文件）") }) {
                                Icon(Icons.Default.Delete, contentDescription = "删除文件夹",
                                    tint = MaterialTheme.colorScheme.error)
                            }
                        }
                    }
                    // 展开时显示子文件
                    if (expanded) {
                        folderFiles.forEach { f ->
                            val fileName = f.path.substringAfter('/')
                            item(key = "file_${f.path}") {
                                Row(
                                    Modifier.fillMaxWidth()
                                        .clickable {
                                            try {
                                                val mime = when {
                                                    f.path.endsWith(".pdf") -> "application/pdf"
                                                    f.path.endsWith(".zip") || f.path.endsWith(".7z") -> "application/zip"
                                                    else -> "image/*"
                                                }
                                                val localFile = java.io.File(
                                                    context.filesDir, "downloads/${f.path}"
                                                )
                                                val uri = if (localFile.exists()) {
                                                    FileProvider.getUriForFile(
                                                        context,
                                                        "com.jmcomic.app.fileprovider",
                                                        localFile
                                                    )
                                                } else {
                                                    Uri.parse(api.fileUrl(f.path))
                                                }
                                                val intent = Intent(Intent.ACTION_VIEW)
                                                intent.setDataAndType(uri, mime)
                                                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                                                val infos = context.packageManager
                                                    .queryIntentActivities(intent, 0)
                                                if (infos.isEmpty()) {
                                                    // 没有可处理的应用，直接尝试打开
                                                    context.startActivity(intent)
                                                } else {
                                                    // 显示自建的应用选择列表
                                                    openTarget = f
                                                    openApps = infos
                                                }
                                            } catch (e: Exception) {
                                                // 忽略打开失败
                                            }
                                        }
                                        .padding(vertical = 6.dp),
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Column(Modifier.weight(1f)) {
                                        Text(
                                            fileName,
                                            style = MaterialTheme.typography.bodyMedium,
                                            maxLines = 1,
                                            overflow = TextOverflow.Ellipsis
                                        )
                                        Text(
                                            formatSize(f.size) + formatTime(f.time),
                                            style = MaterialTheme.typography.bodySmall
                                        )
                                    }
                                    IconButton(onClick = { pendingDelete = Pair(f.path, "文件「$fileName」") }) {
                                        Icon(Icons.Default.Delete, contentDescription = "删除",
                                            tint = MaterialTheme.colorScheme.error)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // 删除确认对话框
    pendingDelete?.let { (path, desc) ->
        AlertDialog(
            onDismissRequest = { pendingDelete = null },
            title = { Text("确认删除") },
            text = { Text("确定要删除$desc 吗？此操作不可恢复。") },
            confirmButton = {
                TextButton(onClick = {
                    pendingDelete = null
                    scope.launch {
                        api.deletePath(path)
                        refreshKey++
                    }
                }) { Text("删除", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = {
                TextButton(onClick = { pendingDelete = null }) { Text("取消") }
            }
        )
    }

    // 选择打开方式对话框（自建列表，兼容所有手机）
    val target = openTarget
    val apps = openApps
    if (target != null && apps != null) {
        val mime = when {
            target.path.endsWith(".pdf") -> "application/pdf"
            target.path.endsWith(".zip") || target.path.endsWith(".7z") -> "application/zip"
            else -> "image/*"
        }
        AlertDialog(
            onDismissRequest = { openApps = null; openTarget = null },
            title = { Text("选择打开方式") },
            text = {
                val pm = context.packageManager
                LazyColumn(Modifier.height(300.dp)) {
                    apps.forEach { info ->
                        // key 必须唯一：同一应用可能有多个可处理该类型的 Activity
                        item(key = info.activityInfo.packageName + "/" + info.activityInfo.name) {
                            val label = info.loadLabel(pm).toString()
                            val icon: Drawable? = info.loadIcon(pm)
                            Row(
                                Modifier.fillMaxWidth()
                                    .clickable {
                                        openApps = null
                                        openTarget = null
                                        try {
                                            val localFile = java.io.File(
                                                context.filesDir, "downloads/${target.path}"
                                            )
                                            val uri = if (localFile.exists()) {
                                                FileProvider.getUriForFile(
                                                    context,
                                                    "com.jmcomic.app.fileprovider",
                                                    localFile
                                                )
                                            } else {
                                                Uri.parse(api.fileUrl(target.path))
                                            }
                                            val targetIntent = Intent(Intent.ACTION_VIEW)
                                            targetIntent.setDataAndType(uri, mime)
                                            targetIntent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                                            targetIntent.setClassName(
                                                info.activityInfo.packageName,
                                                info.activityInfo.name
                                            )
                                            context.startActivity(targetIntent)
                                        } catch (e: Exception) {
                                            // 忽略打开失败
                                        }
                                    }
                                    .padding(vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                icon?.let {
                                    Image(
                                        bitmap = it.toBitmap().asImageBitmap(),
                                        contentDescription = null,
                                        modifier = Modifier.size(32.dp).padding(end = 8.dp)
                                    )
                                }
                                Text(label, style = MaterialTheme.typography.bodyMedium)
                            }
                        }
                    }
                }
            },
            confirmButton = {},
            dismissButton = {
                TextButton(onClick = { openApps = null; openTarget = null }) { Text("取消") }
            }
        )
    }
}

/** Drawable -> Bitmap（供应用图标显示） */
private fun Drawable.toBitmap(): android.graphics.Bitmap {
    val w = intrinsicWidth.coerceAtLeast(1)
    val h = intrinsicHeight.coerceAtLeast(1)
    val bitmap = android.graphics.Bitmap.createBitmap(w, h, android.graphics.Bitmap.Config.ARGB_8888)
    val canvas = android.graphics.Canvas(bitmap)
    setBounds(0, 0, w, h)
    draw(canvas)
    return bitmap
}

private fun formatSize(size: Long): String {
    if (size <= 0) return "-"
    val kb = size / 1024.0
    if (kb < 1024) return String.format(Locale.CHINA, "%.0f KB", kb)
    val mb = kb / 1024.0
    if (mb < 1024) return String.format(Locale.CHINA, "%.1f MB", mb)
    val gb = mb / 1024.0
    return String.format(Locale.CHINA, "%.2f GB", gb)
}

private fun formatTime(time: Long): String {
    if (time <= 0) return ""
    val sdf = java.text.SimpleDateFormat("MM-dd HH:mm", Locale.CHINA)
    return sdf.format(java.util.Date(time * 1000))
}

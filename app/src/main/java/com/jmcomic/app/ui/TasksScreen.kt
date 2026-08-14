package com.jmcomic.app.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.jmcomic.app.api.BackendApi
import com.jmcomic.app.api.TaskInfo
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@Composable
fun TasksScreen(api: BackendApi) {
    var tasks by remember { mutableStateOf<List<TaskInfo>>(emptyList()) }
    var loaded by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    // 每 3 秒轮询任务状态
    LaunchedEffect(api) {
        while (true) {
            tasks = api.getTasks()
            loaded = true
            delay(3000)
        }
    }

    Column(Modifier.fillMaxSize().padding(horizontal = 12.dp)) {
        Text("📥 下载任务", style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.padding(vertical = 8.dp))
        if (!loaded) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
        } else if (tasks.isEmpty()) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("暂无任务\n\n在「搜索」页提交下载后，这里会显示进度",
                    style = MaterialTheme.typography.bodyMedium)
            }
        } else {
            LazyColumn {
                items(tasks) { t ->
                    TaskRow(t, onCancel = { id ->
                        scope.launch { api.cancelTask(id) }
                    })
                }
            }
        }
    }
}

@Composable
fun TaskRow(task: TaskInfo, onCancel: (String) -> Unit) {
    val statusColor = when (task.status) {
        "done" -> Color(0xFF4CAF50)
        "failed" -> Color(0xFFF44336)
        "cancelled" -> Color.Gray
        "running" -> Color(0xFFFF9800)
        else -> Color.Gray
    }
    val canCancel = task.status == "running" || task.status == "pending"
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "ID: ${task.id}",
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.weight(1f)
            )
            if (canCancel) {
                TextButton(onClick = { onCancel(task.id) }) { Text("取消") }
            }
            Text(
                when (task.status) {
                    "done" -> "✅ 完成"
                    "failed" -> "❌ 失败"
                    "cancelled" -> "⏹ 已取消"
                    "running" -> "⏳ 下载中"
                    "pending" -> "⏸ 排队中"
                    else -> task.status
                },
                color = statusColor,
                style = MaterialTheme.typography.bodySmall
            )
        }
        Spacer(Modifier.height(4.dp))
        LinearProgressIndicator(
            progress = { (task.progress / 100f).coerceIn(0f, 1f) },
            modifier = Modifier.fillMaxWidth().height(6.dp)
        )
        Spacer(Modifier.height(2.dp))
        Text(task.message, style = MaterialTheme.typography.bodySmall)
        Spacer(Modifier.height(4.dp))
    }
}

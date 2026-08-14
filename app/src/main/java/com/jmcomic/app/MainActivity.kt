package com.jmcomic.app

import android.content.Context
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.core.content.edit
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.jmcomic.app.api.BackendApi
import com.jmcomic.app.api.DownloadSettings
import com.jmcomic.app.ui.FilesScreen
import com.jmcomic.app.ui.SearchScreen
import com.jmcomic.app.ui.SettingsScreen
import com.jmcomic.app.ui.TasksScreen
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject

class MainActivity : ComponentActivity() {

    companion object {
        // 内嵌 Python 服务状态（供界面显示）
        var pyStatus = mutableStateOf("正在启动 Python 引擎...")
        var pyError = mutableStateOf<String?>(null)
        // 主题模式：system=跟随系统 light=浅色 dark=深色
        var themeMode = mutableStateOf("system")
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // 读取保存的主题设置
        try {
            MainActivity.themeMode.value = getSharedPreferences("jmcomic", Context.MODE_PRIVATE)
                .getString("theme", "system") ?: "system"
        } catch (e: Exception) {
            // 忽略
        }
        // 启动内嵌 Python 服务（jmcomic 本地运行，独立版无需电脑）
        startPythonService()
        setContent {
            // 主题：跟随系统 / 浅色 / 深色（三选一）
            val darkTheme = when (MainActivity.themeMode.value) {
                "dark" -> true
                "light" -> false
                else -> androidx.compose.foundation.isSystemInDarkTheme()
            }
            MaterialTheme(
                colorScheme = if (darkTheme) {
                    androidx.compose.material3.darkColorScheme()
                } else {
                    androidx.compose.material3.lightColorScheme()
                }
            ) {
                AppRoot()
            }
        }
    }

    /** 启动内嵌 Python 服务（独立版：jmcomic 在手机本地运行） */
    private fun startPythonService() {
        Thread {
            try {
                pyStatus.value = "正在初始化 Python..."
                Python.start(AndroidPlatform(applicationContext))
                pyStatus.value = "正在加载下载引擎..."
                val py = Python.getInstance()
                val module = py.getModule("main")
                // 下载目录使用 filesDir 下的 downloads 子目录，避免和 Python 运行时文件混在一起
                val downloadDir = java.io.File(filesDir, "downloads").absolutePath
                module.callAttr("set_download_dir", downloadDir)
                // 清除上次运行的日志（应用关闭后日志不留存，日志在 downloads 外的独立目录）
                try {
                    java.io.File(filesDir, "logs/error.log").delete()
                } catch (e: Exception) {
                    // 忽略
                }
                // 应用设置里保存的代理（预览/查询/下载都要走代理）
                try {
                    val sp = getSharedPreferences("jmcomic", Context.MODE_PRIVATE)
                    val saved = sp.getString("settings", null)
                    if (saved != null) {
                        val proxy = JSONObject(saved).optString("proxy", "")
                        if (proxy.isNotBlank()) {
                            module.callAttr("set_proxy", proxy)
                        }
                    }
                } catch (e: Exception) {
                    // 忽略代理读取失败
                }
                pyStatus.value = "正在启动本地服务..."
                module.callAttr("start")
            } catch (e: Throwable) {
                pyError.value = e.toString() + "\n" +
                    (e.stackTrace.take(5).joinToString("\n") { "  at " + it.toString() })
                pyStatus.value = "启动失败"
                e.printStackTrace()
            }
        }.start()
    }
}

@Composable
fun AppRoot() {
    val context = LocalContext.current
    val prefs = remember(context) {
        context.getSharedPreferences("jmcomic", Context.MODE_PRIVATE)
    }
    // 独立版：固定使用手机本地服务
    val api = remember { BackendApi("http://127.0.0.1:5000") }
    var tab by remember { mutableIntStateOf(0) }

    // 下载设置（持久化保存）
    var settings by remember {
        mutableStateOf(
            prefs.getString("settings", null)
                ?.let { runCatching { DownloadSettings.fromJson(JSONObject(it)) }.getOrNull() }
                ?: DownloadSettings()
        )
    }
    fun saveSettings(s: DownloadSettings) {
        settings = s
        prefs.edit { putString("settings", s.toJson().toString()) }
    }

    // 切换主题并保存
    fun setTheme(mode: String) {
        MainActivity.themeMode.value = mode
        prefs.edit { putString("theme", mode) }
    }

    // 实时检测本地服务是否就绪
    var serverReady by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        while (true) {
            serverReady = try {
                val conn = java.net.URL("http://127.0.0.1:5000/")
                    .openConnection() as java.net.HttpURLConnection
                conn.connectTimeout = 1000
                conn.readTimeout = 1000
                conn.responseCode == 200
            } catch (e: Exception) {
                false
            }
            kotlinx.coroutines.delay(1000)
        }
    }

    Scaffold(
        bottomBar = {
            NavigationBar {
                NavigationBarItem(
                    selected = tab == 0,
                    onClick = { tab = 0 },
                    icon = { Icon(Icons.Default.Search, null) },
                    label = { Text("搜索") }
                )
                NavigationBarItem(
                    selected = tab == 1,
                    onClick = { tab = 1 },
                    icon = { Icon(Icons.AutoMirrored.Filled.List, null) },
                    label = { Text("任务") }
                )
                NavigationBarItem(
                    selected = tab == 2,
                    onClick = { tab = 2 },
                    icon = { Icon(Icons.Default.Folder, null) },
                    label = { Text("文件") }
                )
                NavigationBarItem(
                    selected = tab == 3,
                    onClick = { tab = 3 },
                    icon = { Icon(Icons.Default.Settings, null) },
                    label = { Text("设置") }
                )
            }
        }
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            when (tab) {
                0 -> SearchScreen(api, settings)
                1 -> TasksScreen(api)
                2 -> FilesScreen(api)
                3 -> SettingsScreen(
                    settings,
                    ::saveSettings,
                    MainActivity.themeMode.value,
                    ::setTheme
                )
            }
        }
    }
}

package com.jmcomic.app.ui

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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.ui.unit.dp
import com.jmcomic.app.api.DownloadSettings

/**
 * 设置界面：与电脑版的功能对齐（下载/代理/路径/PDF/ZIP/封面/跳过/登录）
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    settings: DownloadSettings,
    onUpdate: (DownloadSettings) -> Unit,
    themeMode: String = "system",
    onThemeChange: (String) -> Unit = {},
) {
    var showLogs by remember { mutableStateOf(false) }
    val context = LocalContext.current

    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 12.dp)) {
        item { SectionTitle("外观") }
        item {
            Row(
                Modifier.fillMaxWidth().padding(bottom = 4.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                listOf(
                    "system" to "跟随系统",
                    "light" to "浅色",
                    "dark" to "深色",
                ).forEach { (mode, label) ->
                    TextButton(
                        onClick = { onThemeChange(mode) },
                        contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 10.dp)
                    ) {
                        Text(
                            label,
                            style = MaterialTheme.typography.bodyMedium,
                            color = if (themeMode == mode) MaterialTheme.colorScheme.primary
                            else MaterialTheme.colorScheme.onSurface
                        )
                    }
                }
            }
        }

        // 账号登录（第二位）
        item { SectionTitle("账号登录") }
        item { ToggleSetting("启用登录（下载前登录）", settings.login) {
            onUpdate(settings.copy(login = it))
        } }
        if (settings.login) {
            item {
                OutlinedTextField(
                    value = settings.username,
                    onValueChange = { onUpdate(settings.copy(username = it)) },
                    label = { Text("用户名") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true
                )
            }
            item {
                OutlinedTextField(
                    value = settings.password,
                    onValueChange = { onUpdate(settings.copy(password = it)) },
                    label = { Text("密码") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true
                )
            }
        }

        item { SectionTitle("下载设置") }

        item { SliderSetting("图片并发数: ${settings.imageThreads}", settings.imageThreads, 1..32) {
            onUpdate(settings.copy(imageThreads = it))
        } }
        item { SliderSetting("章节并发数: ${settings.photoThreads}", settings.photoThreads, 1..8) {
            onUpdate(settings.copy(photoThreads = it))
        } }
        item { ToggleSetting("解密图片（禁漫图片已加密）", settings.decode) {
            onUpdate(settings.copy(decode = it))
        } }
        item { ToggleSetting("启用缓存（跳过已下载）", settings.cache) {
            onUpdate(settings.copy(cache = it))
        } }

        item { SectionTitle("客户端与网络") }
        item {
            DropdownSetting("客户端类型", settings.clientType, DownloadSettings.CLIENT_TYPES) {
                onUpdate(settings.copy(clientType = it))
            }
        }
        item { SliderSetting("重试次数: ${settings.retryTimes}", settings.retryTimes, 0..20) {
            onUpdate(settings.copy(retryTimes = it))
        } }
        item {
            OutlinedTextField(
                value = settings.proxy,
                onValueChange = { onUpdate(settings.copy(proxy = it)) },
                label = { Text("HTTP 代理（留空不代理）") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true
            )
        }

        item { SectionTitle("保存路径规则") }
        item {
            DropdownSetting(
                "路径规则",
                settings.rule,
                DownloadSettings.RULES,
                labelFor = { DownloadSettings.RULES_LABEL[settings.rule] ?: settings.rule },
                optionLabels = DownloadSettings.RULES.map {
                    DownloadSettings.RULES_LABEL[it] ?: it
                },
                onSelect = { onUpdate(settings.copy(rule = it)) }
            )
        }

        item { SectionTitle("转 PDF") }
        item { ToggleSetting("下载后自动转为 PDF", settings.pdf) {
            onUpdate(settings.copy(pdf = it))
        } }
        if (settings.pdf) {
            item {
                OutlinedTextField(
                    value = settings.pdfPassword,
                    onValueChange = { onUpdate(settings.copy(pdfPassword = it)) },
                    label = { Text("PDF 密码（留空不加密）") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true
                )
            }
            item { ToggleSetting("转换后删除原图片", settings.pdfDelete) {
                onUpdate(settings.copy(pdfDelete = it))
            } }
            item {
                OutlinedTextField(
                    value = settings.pdfRule,
                    onValueChange = { onUpdate(settings.copy(pdfRule = it)) },
                    label = { Text("文件名规则（{Aid}=本子ID {Pname}=章节名）") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true
                )
            }
        }

        item { SectionTitle("压缩 ZIP") }
        item { ToggleSetting("下载后压缩为 ZIP", settings.zip) {
            onUpdate(settings.copy(zip = it))
        } }
        if (settings.zip) {
            item {
                DropdownSetting("压缩格式", settings.zipFormat, DownloadSettings.ZIP_FORMATS) {
                    onUpdate(settings.copy(zipFormat = it))
                }
            }
            item {
                DropdownSetting("压缩级别", settings.zipLevel, DownloadSettings.ZIP_LEVELS) {
                    onUpdate(settings.copy(zipLevel = it))
                }
            }
            item {
                OutlinedTextField(
                    value = settings.zipPassword,
                    onValueChange = { onUpdate(settings.copy(zipPassword = it)) },
                    label = { Text("压缩密码（7z/加密需填写）") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true
                )
            }
            item { ToggleSetting("压缩后删除原文件", settings.zipDelete) {
                onUpdate(settings.copy(zipDelete = it))
            } }
        }

        item { SectionTitle("其他") }
        item { ToggleSetting("下载封面图", settings.cover) {
            onUpdate(settings.copy(cover = it))
        } }
        item { SectionTitle("诊断") }
        item {
            TextButton(onClick = { showLogs = true }) {
                Text("📋 查看日志")
            }
        }
        item { Spacer(Modifier.height(24.dp)) }
    }

    // 查看日志对话框
    if (showLogs) {
        val logContent = remember { readLogFile(context) }
        AlertDialog(
            onDismissRequest = { showLogs = false },
            title = { Text("运行日志") },
            text = {
                Column(Modifier.height(320.dp)) {
                    Text(
                        logContent,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier
                            .fillMaxWidth()
                            .verticalScroll(rememberScrollState())
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = { showLogs = false }) { Text("关闭") }
            }
        )
    }
}

/** 读取日志文件内容（日志在 downloads 外的独立目录） */
private fun readLogFile(context: android.content.Context): String {
    return try {
        val f = java.io.File(context.filesDir, "logs/error.log")
        if (f.exists() && f.length() > 0) f.readText() else "暂无日志（应用本次运行还没有产生日志）"
    } catch (e: Exception) {
        "读取日志失败: ${e.message}"
    }
}

@Composable
private fun SectionTitle(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.titleSmall,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(top = 14.dp, bottom = 4.dp)
    )
}

@Composable
private fun ToggleSetting(text: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(text, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = onChange)
    }
}

@Composable
private fun SliderSetting(
    label: String,
    value: Int,
    range: IntRange,
    onChange: (Int) -> Unit,
) {
    Column(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
        Text(label, style = MaterialTheme.typography.bodyMedium)
        Slider(
            value = value.toFloat(),
            onValueChange = { onChange(it.toInt()) },
            valueRange = range.first.toFloat()..range.last.toFloat(),
            steps = (range.last - range.first - 1).coerceAtLeast(0)
        )
    }
}

@Composable
@OptIn(ExperimentalMaterial3Api::class)
private fun DropdownSetting(
    label: String,
    selected: String,
    options: List<String>,
    labelFor: (() -> String)? = null,
    optionLabels: List<String>? = null,  // 每个选项的显示文字（与 options 一一对应）
    onSelect: (String) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(expanded = expanded, onExpandedChange = { expanded = it }) {
        OutlinedTextField(
            value = labelFor?.invoke() ?: selected,
            onValueChange = {},
            readOnly = true,
            label = { Text(label) },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
            modifier = Modifier.menuAnchor().fillMaxWidth(),
            singleLine = true
        )
        ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            options.forEachIndexed { i, opt ->
                DropdownMenuItem(
                    text = { Text(optionLabels?.getOrNull(i) ?: opt) },
                    onClick = { onSelect(opt); expanded = false }
                )
            }
        }
    }
}

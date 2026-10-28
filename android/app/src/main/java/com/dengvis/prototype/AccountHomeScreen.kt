package com.dengvis.prototype

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.ZoneOffset

@Composable
fun AccountHomeScreen(api: JarvisApi, token: String, onOpenDayDemo: () -> Unit, modifier: Modifier = Modifier) {
    val scope = rememberCoroutineScope()
    var report by remember(token) { mutableStateOf<LifeMorning?>(null) }
    var entries by remember(token) { mutableStateOf<List<LifeSaved>>(emptyList()) }
    var devices by remember(token) { mutableStateOf<List<PcDevice>>(emptyList()) }
    var message by remember(token) { mutableStateOf("") }
    var busy by remember(token) { mutableStateOf(false) }

    suspend fun refresh() {
        if (busy) return
        busy = true
        message = ""
        try {
            report = api.morning(token, LocalDate.now(ZoneOffset.ofHours(8)).toString())
            entries = api.lifeItems(token)
            devices = api.pcDevices(token)
        } catch (error: Exception) {
            message = error.message ?: "首页暂时无法更新，请稍后重试。"
        } finally {
            busy = false
        }
    }

    LaunchedEffect(token) { refresh() }
    val tasks = entries.filter { it.kind == "task" && it.status == "open" }
    val schedules = entries.filter { it.kind == "schedule" && it.status == "planned" }
    val pcStatus = if (devices.none { !it.revoked }) "未配对"
        else if (devices.any { it.online && !it.revoked }) "在线" else "离线"

    LazyColumn(modifier = modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Text("首页", style = MaterialTheme.typography.titleLarge)
            Button(onClick = onOpenDayDemo) { Text("体验固定的一天") }
            Text("大学生的一天 · 固定演示内容；任务仍需你确认才会保存。", style = MaterialTheme.typography.bodySmall)
            Button(onClick = { scope.launch { refresh() } }, enabled = !busy) { Text("刷新首页") }
            if (busy && report == null) Text("正在读取今日状态…")
            if (message.isNotBlank()) Text(message, color = MaterialTheme.colorScheme.error)
        }
        report?.let { today ->
            item {
                Text("今日晨报 · ${today.date}", style = MaterialTheme.typography.titleMedium)
                Text("待办 ${today.tasks} 项 · 日程 ${today.schedules} 项 · PC $pcStatus")
                val sleep = when (today.sleepStatus) {
                    "not_authorized" -> "未授权"
                    "not_synced" -> "未同步"
                    "failed" -> "获取失败"
                    else -> "可用"
                }
                Text("睡眠数据：$sleep", style = MaterialTheme.typography.bodySmall)
            }
        }
        item { Text("当前待办", style = MaterialTheme.typography.titleMedium) }
        if (tasks.isEmpty()) item { Text("暂无未完成待办。") }
        items(tasks, key = { "task-${it.id}" }) { entry ->
            Text("• ${entry.title}", modifier = Modifier.padding(vertical = 2.dp))
        }
        item { Text("当前日程", style = MaterialTheme.typography.titleMedium) }
        if (schedules.isEmpty()) item { Text("暂无进行中的日程。") }
        items(schedules, key = { "schedule-${it.id}" }) { entry ->
            Column(modifier = Modifier.padding(vertical = 2.dp)) {
                Text("• ${entry.title}")
                entry.startsAt?.let { Text(it.take(16), style = MaterialTheme.typography.bodySmall) }
            }
        }
    }
}

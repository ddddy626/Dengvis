package com.dengvis.prototype

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
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
import java.time.Instant
import java.time.temporal.ChronoUnit

@Composable
fun AccountMemoryScreen(api: JarvisApi, token: String, modifier: Modifier = Modifier) {
    val scope = rememberCoroutineScope()
    var summary by remember { mutableStateOf("") }
    var purpose by remember { mutableStateOf("planning") }
    var candidates by remember { mutableStateOf<List<MemoryCandidate>>(emptyList()) }
    var busy by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf("") }
    var deleteTarget by remember { mutableStateOf<MemoryCandidate?>(null) }

    LaunchedEffect(token) {
        try { candidates = api.memoryCandidates(token) }
        catch (error: Exception) { message = error.message ?: "暂时无法读取记忆。" }
    }

    fun runAction(action: suspend () -> Unit) {
        if (busy) return
        busy = true; message = ""
        scope.launch {
            try { action(); candidates = api.memoryCandidates(token) }
            catch (error: Exception) { message = error.message ?: "操作失败，请重试。" }
            finally { busy = false }
        }
    }

    deleteTarget?.let { target ->
        AlertDialog(
            onDismissRequest = { deleteTarget = null },
            title = { Text("删除记忆记录？") },
            text = { Text("候选和已确认的记忆将被删除。已经保存的任务会保留。") },
            confirmButton = { Button(onClick = {
                deleteTarget = null
                runAction { api.deleteMemoryCandidate(token, target.id); message = "记忆记录已删除。" }
            }, enabled = !busy) { Text("删除") } },
            dismissButton = { Button(onClick = { deleteTarget = null }) { Text("保留") } },
        )
    }

    LazyColumn(modifier = modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Text("我的记忆", style = MaterialTheme.typography.titleLarge)
            Text("候选记忆需要单独批准。撤销后立即停止用于规划。", style = MaterialTheme.typography.bodySmall)
            OutlinedTextField(value = summary, onValueChange = { summary = it }, label = { Text("希望 Jarvis 记住什么？") },
                modifier = Modifier.fillMaxWidth(), enabled = !busy)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { purpose = "planning" }, enabled = !busy && purpose != "planning") { Text("用于规划") }
                Button(onClick = { purpose = "conversation" }, enabled = !busy && purpose != "conversation") { Text("用于对话") }
            }
            Text("当前用途：${if (purpose == "planning") "规划" else "对话"}；默认 30 天有效。")
            Button(onClick = {
                runAction {
                    api.createMemoryCandidate(token, summary.trim(), purpose,
                        Instant.now().plus(30, ChronoUnit.DAYS).toString())
                    summary = ""; message = "候选记忆已创建，等待你批准。"
                }
            }, enabled = !busy && summary.isNotBlank() && summary.length <= 1000) { Text("创建候选记忆") }
        }
        if (message.isNotBlank()) item { Text(message, color = MaterialTheme.colorScheme.primary) }
        items(candidates, key = { it.id }) { item ->
            Column(modifier = Modifier.padding(vertical = 4.dp)) {
                Text("#${item.id} · ${when (item.status) { "candidate" -> "待批准"; "confirmed" -> "已批准"; "rejected" -> "已拒绝/撤销"; else -> "已过期" }}")
                Text("来源：${item.evidenceRef}；用途：${if (item.purpose == "planning") "规划" else "对话"}；有效期至 ${item.expiresAt.take(10)}", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(value = item.summary, onValueChange = { value ->
                    candidates = candidates.map { if (it.id == item.id) it.copy(summary = value) else it }
                }, label = { Text("内容") }, modifier = Modifier.fillMaxWidth(), enabled = !busy && item.status in listOf("candidate", "confirmed"))
                if (item.status in listOf("candidate", "confirmed")) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = { runAction { api.editMemoryCandidate(token, item); message = "记忆已更新。" } }, enabled = !busy && item.summary.isNotBlank()) { Text("保存修改") }
                        Button(onClick = { runAction { api.editMemoryCandidate(token, item.copy(expiresAt = Instant.now().plus(30, ChronoUnit.DAYS).toString())); message = "有效期已更新。" } }, enabled = !busy) { Text("续 30 天") }
                    }
                }
                if (item.status == "candidate") {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = { runAction { api.decideMemoryCandidate(token, item.id, true); message = "已批准。" } }, enabled = !busy) { Text("批准") }
                        Button(onClick = { runAction { api.decideMemoryCandidate(token, item.id, false); message = "已拒绝。" } }, enabled = !busy) { Text("拒绝") }
                    }
                }
                if (item.status == "confirmed") Button(onClick = { runAction { api.revokeMemoryCandidate(token, item.id); message = "已撤销。" } }, enabled = !busy) { Text("撤销记忆") }
                Button(onClick = { deleteTarget = item }, enabled = !busy) { Text("删除记录") }
            }
        }
    }
}

package com.dengvis.prototype

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.Button
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
import java.util.UUID

@Composable
fun AccountStudyScreen(api: JarvisApi, token: String, modifier: Modifier = Modifier) {
    val scope = rememberCoroutineScope()
    var pair by remember { mutableStateOf<PairCode?>(null) }
    var devices by remember { mutableStateOf<List<PcDevice>>(emptyList()) }
    var jobs by remember { mutableStateOf<List<StudyJob>>(emptyList()) }
    var proposed by remember { mutableStateOf<LifePlan?>(null) }
    var studyQuestions by remember { mutableStateOf<List<String>>(emptyList()) }
    var pendingSuggestion by remember { mutableStateOf<LifeSuggestion?>(null) }
    var pendingSuggestionJob by remember { mutableStateOf<Long?>(null) }
    var pendingDraftKey by remember { mutableStateOf("") }
    var query by remember { mutableStateOf("") }
    var pendingKey by remember { mutableStateOf("") }
    var pendingQuery by remember { mutableStateOf("") }
    var message by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }

    LaunchedEffect(token) {
        try { devices = api.pcDevices(token); jobs = api.studyJobs(token) }
        catch (error: Exception) { message = error.message ?: "暂时无法读取 PC 状态。" }
    }

    fun runAction(action: suspend () -> Unit) {
        if (busy) return
        busy = true; message = ""
        scope.launch {
            try { action() }
            catch (error: Exception) { message = error.message ?: "操作失败，请重试。" }
            finally { busy = false }
        }
    }

    LazyColumn(modifier = modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Text("本地学习", style = MaterialTheme.typography.titleLarge)
            Text("电脑只扫描你启动 Worker 时指定的 PDF 目录；服务端只收到少量检索片段。", style = MaterialTheme.typography.bodySmall)
            Button(onClick = { runAction { pair = api.createPcPairCode(token); message = "请在十分钟内到电脑完成配对。" } }, enabled = !busy) { Text("生成 PC 配对码") }
            pair?.let { code ->
                Text("配对码（可长按复制）：")
                SelectionContainer { Text(code.code) }
                Text("有效期至 ${code.expiresAt.take(19)}；只可使用一次。", style = MaterialTheme.typography.bodySmall)
            }
        }
        item {
            Text("已配对设备", style = MaterialTheme.typography.titleMedium)
            Button(onClick = { runAction { devices = api.pcDevices(token) } }, enabled = !busy) { Text("刷新设备") }
        }
        items(devices, key = { it.id }) { device ->
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(vertical = 4.dp)) {
                Text("PC #${device.id} · ${if (device.revoked) "已撤销" else if (device.online) "在线" else "离线"}", modifier = Modifier.weight(1f))
                if (!device.revoked) Button(onClick = { runAction { api.revokePcDevice(token, device.id); devices = api.pcDevices(token) } }, enabled = !busy) { Text("撤销") }
            }
        }
        item {
            Text("发起学习任务", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(value = query, onValueChange = { query = it }, label = { Text("想从本地资料中查找什么？") },
                modifier = Modifier.fillMaxWidth(), enabled = !busy)
            Button(onClick = {
                val input = query.trim()
                runAction {
                    if (pendingQuery != input) { pendingQuery = input; pendingKey = UUID.randomUUID().toString().replace("-", "") }
                    api.createStudyJob(token, input, pendingKey)
                    jobs = api.studyJobs(token)
                    pendingKey = ""; pendingQuery = ""; query = ""
                    message = "已排队；PC 离线时会等待。"
                }
            }, enabled = !busy && query.isNotBlank() && query.length <= 500) { Text("提交任务") }
        }
        item {
            Text("学习任务", style = MaterialTheme.typography.titleMedium)
            Button(onClick = { runAction { jobs = api.studyJobs(token); devices = api.pcDevices(token) } }, enabled = !busy) { Text("刷新状态") }
        }
        val draft = proposed
        if (draft != null) {
            item {
                Text("学习待办草案 · 尚未写入", style = MaterialTheme.typography.titleMedium)
                Text("请检查来源和事项后决定。")
                if (studyQuestions.isNotEmpty()) Text("需要你补充：${studyQuestions.joinToString("；")}")
            }
            items(draft.items.indices.toList()) { index ->
                val entry = proposed?.items?.getOrNull(index)
                if (entry != null) OutlinedTextField(value = entry.title, onValueChange = { title ->
                    proposed = proposed?.copy(items = proposed!!.items.toMutableList().also { it[index] = entry.copy(title = title) })
                }, label = { Text("待办 ${index + 1}") }, modifier = Modifier.fillMaxWidth(), enabled = !busy)
            }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { runAction {
                        val edited = api.editLifePlan(token, proposed ?: return@runAction)
                        api.decideLifePlan(token, edited.jobId, true)
                        proposed = null; pendingSuggestion = null; pendingSuggestionJob = null; pendingDraftKey = ""; studyQuestions = emptyList()
                        message = "学习待办已保存，可在生活任务中查看。"
                    } }, enabled = !busy && draft.items.all { it.title.isNotBlank() }) { Text("批准并保存") }
                    Button(onClick = { runAction {
                        api.decideLifePlan(token, draft.jobId, false)
                        proposed = null; pendingSuggestion = null; pendingSuggestionJob = null; pendingDraftKey = ""; studyQuestions = emptyList()
                        message = "已拒绝，没有写入待办。"
                    } }, enabled = !busy) { Text("拒绝") }
                }
            }
        }
        if (message.isNotBlank()) item { Text(message, color = MaterialTheme.colorScheme.primary) }
        items(jobs, key = { it.id }) { job ->
            Column(modifier = Modifier.padding(vertical = 6.dp)) {
                Text("#${job.id} · ${job.status} · ${job.query}")
                job.modelName?.let { Text("检索：$it；耗时 ${job.elapsedMs ?: 0} 毫秒", style = MaterialTheme.typography.bodySmall) }
                job.error?.let { Text("失败原因：$it", color = MaterialTheme.colorScheme.error) }
                job.excerpts.forEach { excerpt ->
                    Text("${excerpt.source} · 第 ${excerpt.page} 页 · ${excerpt.text}", style = MaterialTheme.typography.bodySmall)
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (job.status == "succeeded" && job.excerpts.isNotEmpty()) Button(onClick = { runAction {
                        val result = api.studyDraft(token, job.id)
                        if (result.status == "waiting_approval") proposed = result
                        else message = "此学习草案已处理，请在生活任务中查看。"
                    } }, enabled = !busy && proposed == null) { Text("生成待办草案") }
                    if (job.status == "failed") Button(onClick = { runAction { api.retryStudyJob(token, job.id); jobs = api.studyJobs(token) } }, enabled = !busy) { Text("重试") }
                    if (job.status in listOf("waiting_pc", "running", "failed")) Button(onClick = { runAction { api.cancelLifeJob(token, job.id); jobs = api.studyJobs(token) } }, enabled = !busy) { Text("取消") }
                }
                if (job.status == "succeeded" && job.excerpts.isNotEmpty()) {
                    Button(onClick = { runAction {
                        if (pendingSuggestionJob != job.id) {
                            pendingSuggestionJob = job.id; pendingSuggestion = null
                            pendingDraftKey = UUID.randomUUID().toString().replace("-", "")
                        }
                        if (pendingSuggestion == null) pendingSuggestion = api.studySuggest(token, job.id)
                        val suggestion = pendingSuggestion ?: return@runAction
                        proposed = api.createLifePlan(token, "根据本地资料安排学习：${job.query}".take(500),
                            pendingDraftKey, suggestion.items)
                        studyQuestions = suggestion.questions
                        message = "云端建议已成为待批准草案；请检查每项来源。"
                    } }, enabled = !busy && proposed == null) { Text("将这三段以内摘录送 DeepSeek 生成建议") }
                }
            }
        }
    }
}

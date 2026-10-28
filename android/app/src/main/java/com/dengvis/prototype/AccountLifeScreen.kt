package com.dengvis.prototype

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
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
import java.time.LocalDate
import java.time.ZoneOffset
import java.util.UUID

@Composable
fun AccountLifeScreen(api: JarvisApi, token: String, modifier: Modifier = Modifier) {
    val scope = rememberCoroutineScope()
    var intent by remember { mutableStateOf("") }
    var useCloudPlan by remember { mutableStateOf(false) }
    var cachedSuggestion by remember { mutableStateOf<LifeSuggestion?>(null) }
    var planQuestions by remember { mutableStateOf<List<String>>(emptyList()) }
    var plan by remember { mutableStateOf<LifePlan?>(null) }
    var saved by remember { mutableStateOf<List<LifeSaved>>(emptyList()) }
    var jobs by remember { mutableStateOf<List<LifeJob>>(emptyList()) }
    var selectedEvents by remember { mutableStateOf<Pair<Long, List<LifeJobEvent>>?>(null) }
    var permissions by remember { mutableStateOf<List<PermissionGrant>>(emptyList()) }
    var morning by remember { mutableStateOf<LifeMorning?>(null) }
    var busy by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf("") }
    var draftKey by remember { mutableStateOf("") }
    var keyedIntent by remember { mutableStateOf("") }
    var keyedCloud by remember { mutableStateOf(false) }

    LaunchedEffect(token) {
        try { saved = api.lifeItems(token); jobs = api.lifeJobs(token); permissions = api.permissions(token) }
        catch (error: Exception) { message = error.message ?: "暂时无法读取生活事项。" }
    }

    fun runAction(action: suspend () -> Unit) {
        if (busy) return
        busy = true
        message = ""
        scope.launch {
            try { action() }
            catch (error: Exception) { message = error.message ?: "操作失败，请重试。" }
            finally { busy = false }
        }
    }

    LazyColumn(modifier = modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Text("生活任务", style = MaterialTheme.typography.titleLarge)
            Text("先检查草案，再决定是否写入账号。", style = MaterialTheme.typography.bodySmall)
            if (permissions.any { it.scope == "life.write" }) {
                Text("已记录本类授权偏好；每份具体清单仍需你确认。", style = MaterialTheme.typography.bodySmall)
                Button(onClick = { runAction {
                    api.revokePermission(token, "life.write")
                    permissions = api.permissions(token)
                    message = "本类授权偏好已撤回。"
                } }, enabled = !busy) { Text("撤回本类偏好") }
            }
        }
        item {
            OutlinedTextField(value = intent, onValueChange = { intent = it }, label = { Text("想安排什么？") },
                modifier = Modifier.fillMaxWidth(), enabled = !busy && plan == null)
            Row {
                Checkbox(checked = useCloudPlan, onCheckedChange = { useCloudPlan = it }, enabled = !busy && plan == null)
                Text("使用云端智能拆解；本次意图会发送给 DeepSeek，草案仍需确认。")
            }
            Button(onClick = {
                val input = intent.trim()
                if (input.isNotEmpty()) runAction {
                    if (keyedIntent != input || keyedCloud != useCloudPlan) {
                        draftKey = UUID.randomUUID().toString().replace("-", "")
                        keyedIntent = input; keyedCloud = useCloudPlan; cachedSuggestion = null
                    }
                    if (useCloudPlan && cachedSuggestion == null) cachedSuggestion = api.suggestLife(token, input)
                    plan = api.createLifePlan(token, input, draftKey, cachedSuggestion?.items)
                    planQuestions = cachedSuggestion?.questions.orEmpty()
                    jobs = api.lifeJobs(token)
                    message = "草案尚未写入。"
                }
            }, enabled = !busy && plan == null && intent.isNotBlank()) { Text("生成草案") }
        }
        val current = plan
        if (current != null) {
            item { Text("待批准的写入清单", style = MaterialTheme.typography.titleMedium) }
            if (planQuestions.isNotEmpty()) item { Text("需要你补充：${planQuestions.joinToString("；")}") }
            items(current.items.indices.toList()) { index ->
                val draft = plan?.items?.getOrNull(index)
                if (draft != null) {
                    Column(modifier = Modifier.padding(vertical = 4.dp)) {
                        Text("${index + 1}. ${if (draft.kind == "task") "待办" else "日程"}")
                        OutlinedTextField(value = draft.title, onValueChange = { value ->
                            plan = plan?.copy(items = plan!!.items.toMutableList().also { it[index] = draft.copy(title = value) })
                        }, label = { Text("标题") }, modifier = Modifier.fillMaxWidth(), enabled = !busy)
                        if (draft.kind == "schedule") {
                            OutlinedTextField(value = draft.startsAt.orEmpty(), onValueChange = { value ->
                                plan = plan?.copy(items = plan!!.items.toMutableList().also { it[index] = draft.copy(startsAt = value) })
                            }, label = { Text("开始：2026-10-17T09:00:00+08:00") }, modifier = Modifier.fillMaxWidth(), enabled = !busy)
                            OutlinedTextField(value = draft.endsAt.orEmpty(), onValueChange = { value ->
                                plan = plan?.copy(items = plan!!.items.toMutableList().also { it[index] = draft.copy(endsAt = value) })
                            }, label = { Text("结束：2026-10-17T10:00:00+08:00") }, modifier = Modifier.fillMaxWidth(), enabled = !busy)
                        }
                        Button(onClick = {
                            plan = plan?.copy(items = plan!!.items.toMutableList().also { it[index] = draft.copy(kind = if (draft.kind == "task") "schedule" else "task", dueAt = null, startsAt = null, endsAt = null) })
                        }, enabled = !busy) { Text("切换待办/日程") }
                    }
                }
            }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = {
                        plan = plan?.copy(items = plan!!.items + LifeDraft("task", ""))
                    }, enabled = !busy && current.items.size < 8) { Text("添加") }
                    Button(onClick = {
                        runAction {
                            val edited = api.editLifePlan(token, plan ?: return@runAction)
                            val approved = api.decideLifePlan(token, edited.jobId, true)
                            saved = api.lifeItems(token)
                            jobs = api.lifeJobs(token)
                            plan = null; draftKey = ""; keyedIntent = ""; cachedSuggestion = null; planQuestions = emptyList(); morning = null
                            message = "已保存 ${approved.items.size} 个事项。"
                        }
                    }, enabled = !busy && current.items.isNotEmpty() && current.items.all { it.title.isNotBlank() }) { Text("批准并保存") }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = {
                        runAction {
                            api.decideLifePlan(token, current.jobId, false)
                            jobs = api.lifeJobs(token)
                            plan = null; draftKey = ""; keyedIntent = ""; cachedSuggestion = null; planQuestions = emptyList()
                            message = "已拒绝，未写入事项。"
                        }
                    }, enabled = !busy) { Text("拒绝") }
                    if (permissions.none { it.scope == "life.write" }) Button(onClick = {
                        runAction {
                            val edited = api.editLifePlan(token, plan ?: return@runAction)
                            val approved = api.decideLifePlan(token, edited.jobId, true, rememberScope = true)
                            saved = api.lifeItems(token)
                            jobs = api.lifeJobs(token)
                            permissions = api.permissions(token)
                            plan = null; draftKey = ""; keyedIntent = ""; cachedSuggestion = null; planQuestions = emptyList(); morning = null
                            message = "已保存 ${approved.items.size} 个事项并记录本类偏好；下次仍需确认。"
                        }
                    }, enabled = !busy && current.items.isNotEmpty() && current.items.all { it.title.isNotBlank() }) {
                        Text("批准并记住本类偏好")
                    }
                }
            }
        }
        if (message.isNotBlank()) item { Text(message, color = MaterialTheme.colorScheme.primary) }
        item { Text("已保存的事项", style = MaterialTheme.typography.titleMedium) }
        if (saved.isEmpty()) item { Text("暂无事项。") }
        items(saved, key = { "${it.kind}-${it.id}" }) { entry ->
            Column(modifier = Modifier.padding(vertical = 4.dp)) {
                Text("${if (entry.kind == "task") "待办" else "日程"} · ${entry.status}")
                OutlinedTextField(value = entry.title, onValueChange = { title ->
                    saved = saved.map { if (it.kind == entry.kind && it.id == entry.id) it.copy(title = title) else it }
                }, label = { Text("标题") }, modifier = Modifier.fillMaxWidth(), enabled = !busy)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { runAction { api.updateLifeItem(token, entry, entry.title.trim(), entry.status); saved = api.lifeItems(token); morning = null; message = "已更新。" } }, enabled = !busy && entry.title.isNotBlank()) { Text("保存") }
                    if (entry.kind == "task") Button(onClick = { runAction { api.updateLifeItem(token, entry, entry.title, "done"); saved = api.lifeItems(token); morning = null } }, enabled = !busy && entry.status != "done") { Text("完成") }
                    Button(onClick = { runAction { api.updateLifeItem(token, entry, entry.title, "cancelled"); saved = api.lifeItems(token); morning = null } }, enabled = !busy && entry.status != "cancelled") { Text("取消") }
                }
            }
        }
        item {
            Text("晨报", style = MaterialTheme.typography.titleMedium)
            Button(onClick = { runAction { morning = api.morning(token, LocalDate.now(ZoneOffset.ofHours(8)).toString()) } }, enabled = !busy) { Text("查看今日晨报") }
            morning?.let { report -> Text("${report.date}：待办 ${report.tasks} 项，日程 ${report.schedules} 项；睡眠数据：${when (report.sleepStatus) { "not_authorized" -> "未授权"; "not_synced" -> "未同步"; "failed" -> "获取失败"; else -> "已同步" }}。") }
        }
        item {
            Text("任务记录", style = MaterialTheme.typography.titleMedium)
            Button(onClick = { runAction { jobs = api.lifeJobs(token) } }, enabled = !busy) { Text("刷新记录") }
        }
        items(jobs, key = { it.id }) { job ->
            Column(modifier = Modifier.padding(vertical = 4.dp)) {
                Text("#${job.id} · ${job.status} · ${job.preview}")
                job.latestEvent?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                Button(onClick = { runAction { selectedEvents = job.id to api.lifeJobEvents(token, job.id) } }, enabled = !busy) { Text("查看过程") }
                if (selectedEvents?.first == job.id) {
                    selectedEvents?.second?.forEach { event -> Text("${event.seq}. ${event.summary}", style = MaterialTheme.typography.bodySmall) }
                }
                if (job.status == "waiting_approval") Button(onClick = {
                    runAction {
                        val restored = api.lifePlan(token, job.id)
                        if (restored.status != "waiting_approval") throw IllegalStateException("草案已处理，请刷新记录。")
                        plan = restored
                        cachedSuggestion = null; planQuestions = emptyList(); draftKey = ""; keyedIntent = ""
                        message = "已恢复待批准草案，请检查后决定。"
                    }
                }, enabled = !busy && plan == null) { Text("恢复草案") }
                if (job.status == "waiting_approval") Button(onClick = {
                    runAction {
                        api.cancelLifeJob(token, job.id)
                        if (plan?.jobId == job.id) { plan = null; cachedSuggestion = null; planQuestions = emptyList() }
                        jobs = api.lifeJobs(token)
                        message = "草案已取消。"
                    }
                }, enabled = !busy) { Text("取消草案") }
            }
        }
    }
}

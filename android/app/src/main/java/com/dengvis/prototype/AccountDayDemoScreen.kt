package com.dengvis.prototype

import android.content.Context
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.UUID

private val demoZone = ZoneId.of("Asia/Shanghai")

private fun demoTime(date: LocalDate, hour: Int): String =
    date.atTime(LocalTime.of(hour, 0)).atZone(demoZone).format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)

@Composable
fun AccountDayDemoScreen(
    api: JarvisApi,
    token: String,
    accountId: Long,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val prefs = remember(context) { context.getSharedPreferences("day_demo_progress", Context.MODE_PRIVATE) }
    val date = remember { LocalDate.now(demoZone) }
    val key = remember(accountId, date) { "account-$accountId-$date" }
    val scope = rememberCoroutineScope()
    var phase by remember(key) { mutableStateOf(prefs.getInt("$key.phase", 0)) }
    var runId by remember(key) {
        mutableStateOf(prefs.getString("$key.run", null) ?: UUID.randomUUID().toString().also {
            prefs.edit().putString("$key.run", it).apply()
        })
    }
    var dayPlanId by remember(key) { mutableStateOf(prefs.getLong("$key.dayPlan", -1L)) }
    var studyPlanId by remember(key) { mutableStateOf(prefs.getLong("$key.studyPlan", -1L)) }
    var dayPlan by remember(key) { mutableStateOf<LifePlan?>(null) }
    var studyPlan by remember(key) { mutableStateOf<LifePlan?>(null) }
    var morning by remember(key) { mutableStateOf<LifeMorning?>(null) }
    var saved by remember(key) { mutableStateOf<List<LifeSaved>>(emptyList()) }
    var message by remember(key) { mutableStateOf("") }
    var busy by remember(key) { mutableStateOf(false) }
    var confirmReset by remember(key) { mutableStateOf(false) }

    fun move(next: Int) {
        phase = next
        prefs.edit().putInt("$key.phase", next).apply()
        message = ""
    }

    suspend fun refresh() {
        morning = api.morning(token, date.toString())
        saved = api.lifeItems(token)
        dayPlan = if (dayPlanId > 0) api.lifePlan(token, dayPlanId) else null
        studyPlan = if (studyPlanId > 0) api.lifePlan(token, studyPlanId) else null
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

    LaunchedEffect(token, accountId, date) {
        try { refresh() }
        catch (error: Exception) { message = error.message ?: "暂时无法读取今天的状态。" }
    }

    val refs = (dayPlan?.saved.orEmpty() + studyPlan?.saved.orEmpty()).map { it.kind to it.id }.toSet()
    val dayItems = saved.filter { (it.kind to it.id) in refs }
    val finished = dayItems.count { it.status == "done" || it.status == "completed" }

    LazyColumn(modifier = modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Text("大学生小林的一天", style = MaterialTheme.typography.titleLarge)
            Text("固定演示 · $date · 第 ${phase + 1}/5 段。点击按钮推进时间，无需等待。")
            Text("剧情和学习摘录是演示样例；晨报与批准后的任务来自当前账号。不会调用收费模型。", style = MaterialTheme.typography.bodySmall)
            Button(onClick = onBack) { Text("返回首页") }
            Button(onClick = { runAction { refresh(); message = "已读取当前账号状态。" } }, enabled = !busy) { Text("刷新状态") }
            if (message.isNotBlank()) Text(message, color = MaterialTheme.colorScheme.primary)
        }

        if (phase == 0) item {
            Text("07:30 · 早晨", style = MaterialTheme.typography.titleMedium)
            Text("演示对话：早上好。先吃早餐、带上水杯，再看看今天有哪些生活小事要安排。")
            val report = morning
            if (report == null) Text("正在读取晨报；若失败请刷新。") else {
                Text("当前账号晨报：待办 ${report.tasks} 项，日程 ${report.schedules} 项。")
                Text("睡眠数据：${when (report.sleepStatus) {
                    "not_authorized" -> "未授权"
                    "not_synced" -> "未同步"
                    "failed" -> "获取失败"
                    else -> "可用"
                }}。不使用虚构健康数值。")
            }
            Button(onClick = { move(1) }) { Text("进入上午安排") }
        }

        if (phase == 1) {
            item {
                Text("09:00 · 安排今天", style = MaterialTheme.typography.titleMedium)
                Text("固定建议：下课后买牛奶和水果；给家人回消息；19:00 洗衣服。生成草案不会写入事项。")
                if (dayPlan == null) Button(onClick = { runAction {
                    val draft = listOf(
                        LifeDraft("task", "下课后买牛奶和水果"),
                        LifeDraft("task", "给家人回消息"),
                        LifeDraft("schedule", "19:00 洗衣服", startsAt = demoTime(date, 19), endsAt = demoTime(date, 20)),
                    )
                    val result = api.createLifePlan(token, "固定演示：安排大学生小林的一天", "daydemo-${runId.replace("-", "")}-day", draft)
                    dayPlan = result
                    dayPlanId = result.jobId
                    prefs.edit().putLong("$key.dayPlan", result.jobId).apply()
                    message = "草案已生成，尚未写入。"
                } }, enabled = !busy) { Text("生成固定草案") }
                val plan = dayPlan
                if (plan != null) {
                    Text("草案 #${plan.jobId} · ${plan.status}")
                    plan.items.forEach { Text("• ${it.title}") }
                    if (plan.status == "waiting_approval") {
                        Text("批准后，这 3 项会真实保存到当前账号。")
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Button(onClick = { runAction {
                                val result = api.decideLifePlan(token, plan.jobId, true)
                                dayPlan = result
                                if (result.status == "succeeded") { saved = api.lifeItems(token); move(2) }
                                else message = "草案未保存（${result.status}），请重新开始。"
                            } }, enabled = !busy) { Text("批准并保存") }
                            Button(onClick = { runAction {
                                api.decideLifePlan(token, plan.jobId, false)
                                dayPlan = null
                                dayPlanId = -1L
                                runId = UUID.randomUUID().toString()
                                prefs.edit().remove("$key.dayPlan").putString("$key.run", runId).apply()
                                message = "已拒绝，未写入任何事项。可重新生成草案。"
                            } }, enabled = !busy) { Text("拒绝") }
                        }
                    } else if (plan.status == "succeeded") {
                        Button(onClick = { move(2) }) { Text("进入下午学习") }
                    } else Button(onClick = {
                        dayPlan = null; dayPlanId = -1L; runId = UUID.randomUUID().toString()
                        prefs.edit().remove("$key.dayPlan").putString("$key.run", runId).apply()
                    }) { Text("重新生成草案") }
                }
            }
        }

        if (phase == 2) item {
            Text("15:30 · 整理明天", style = MaterialTheme.typography.titleMedium)
            Text("内置演示样例《校园生活清单》第 1 页：晚上看一眼明天的课程，提前放好课本、水杯和充电器。此段没有读取你的 PC 文件。")
            Text("如需真实检索，请使用上方“学习”入口并配对 PC。")
            if (studyPlan == null) Button(onClick = { runAction {
                val result = api.createLifePlan(token, "固定演示：根据内置校园生活样例整理明天", "daydemo-${runId.replace("-", "")}-study",
                    listOf(LifeDraft("task", "睡前整理明天要带的课本和充电器")))
                studyPlan = result
                studyPlanId = result.jobId
                prefs.edit().putLong("$key.studyPlan", result.jobId).apply()
                message = "学习待办草案已生成，尚未写入。"
            } }, enabled = !busy) { Text("生成学习待办草案") }
            val plan = studyPlan
            if (plan != null) {
                Text("草案 #${plan.jobId} · ${plan.status}：${plan.items.joinToString("；") { it.title }}")
                if (plan.status == "waiting_approval") Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { runAction {
                        val result = api.decideLifePlan(token, plan.jobId, true)
                        studyPlan = result
                        if (result.status == "succeeded") { saved = api.lifeItems(token); move(3) }
                        else message = "草案未保存（${result.status}）。"
                    } }, enabled = !busy) { Text("批准并保存") }
                    Button(onClick = { runAction {
                        api.decideLifePlan(token, plan.jobId, false)
                        studyPlan = api.lifePlan(token, plan.jobId)
                        move(3)
                    } }, enabled = !busy) { Text("拒绝并继续") }
                } else if (plan.status == "succeeded" || plan.status == "cancelled") {
                    Button(onClick = { move(3) }) { Text("进入傍晚执行") }
                }
            } else Button(onClick = { move(3) }) { Text("跳过学习待办") }
        }

        if (phase == 3) {
            item {
                Text("19:00 · 完成事项", style = MaterialTheme.typography.titleMedium)
                Text("以下是本次演示中你实际批准保存的事项。逐项完成后进入晚间回顾。")
                if (dayItems.isEmpty()) Text("暂未读到本次事项，请刷新状态。")
            }
            items(dayItems, key = { "${it.kind}-${it.id}" }) { entry ->
                Column(modifier = Modifier.padding(vertical = 4.dp)) {
                    Text("${entry.title} · ${if (entry.status in listOf("done", "completed")) "已完成" else "进行中"}")
                    if (entry.status in listOf("open", "planned")) Button(onClick = { runAction {
                        api.updateLifeItem(token, entry, entry.title, if (entry.kind == "task") "done" else "completed")
                        saved = api.lifeItems(token)
                    } }, enabled = !busy) { Text("标记完成") }
                }
            }
            item { Button(onClick = { move(4) }, enabled = dayItems.isNotEmpty()) { Text("进入晚间回顾") } }
        }

        if (phase == 4) item {
            Text("21:30 · 晚间回顾", style = MaterialTheme.typography.titleMedium)
            Text("演示对话：今天推进了 $finished / ${dayItems.size} 项；未完成的仍留在任务页，明天可继续处理。")
            dayItems.forEach { Text("• ${it.title}：${if (it.status in listOf("done", "completed")) "已完成" else "未完成"}") }
            Text("回顾只汇总本次批准的真实事项；没有生成虚构的睡眠或 PC 数据。")
            Button(onClick = { confirmReset = true }) { Text("重新体验一天") }
            if (confirmReset) {
                Text("重新开始只重置演示引导；已经保存的任务不会删除。再次批准会新增事项。")
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = {
                        runId = UUID.randomUUID().toString()
                        dayPlanId = -1L; studyPlanId = -1L
                        dayPlan = null; studyPlan = null
                        prefs.edit().putString("$key.run", runId).remove("$key.dayPlan").remove("$key.studyPlan").apply()
                        confirmReset = false
                        move(0)
                    }) { Text("确认重置引导") }
                    Button(onClick = { confirmReset = false }) { Text("取消") }
                }
            }
        }
    }
}

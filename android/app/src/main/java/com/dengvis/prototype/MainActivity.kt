package com.dengvis.prototype

import android.content.pm.ApplicationInfo
import android.os.Bundle
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.speech.RecognizerIntent
import android.speech.tts.TextToSpeech
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.clickable
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import java.util.Locale

private const val LOCAL_API = "http://10.0.2.2:8000"

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) { AccountChatScreen() }
            }
        }
    }
}

@Composable
private fun AccountChatScreen() {
    val context = LocalContext.current
    val isDebug = remember { context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0 }
    val configuredOrigin = remember { context.getString(R.string.api_base_url) }
    val serverReady = isDebug || configuredOrigin.isNotBlank()
    val store = remember { SecureSessionStore(context) }
    val api = remember(isDebug, configuredOrigin) {
        JarvisApi(if (isDebug) LOCAL_API else configuredOrigin, allowLocalHttp = isDebug)
    }
    val scope = rememberCoroutineScope()
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var registering by remember { mutableStateOf(false) }
    var token by remember { mutableStateOf<String?>(null) }
    var account by remember { mutableStateOf<Account?>(null) }
    var draft by remember { mutableStateOf("") }
    var messages by remember { mutableStateOf<List<ChatMessage>>(emptyList()) }
    var status by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var restoring by remember { mutableStateOf(true) }
    var selectedPage by remember { mutableStateOf("home") }
    var hudSnapshot by remember { mutableStateOf<String?>(null) }
    var speaker by remember { mutableStateOf<TextToSpeech?>(null) }
    var speakerReady by remember { mutableStateOf(false) }
    val voiceLauncher = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            val recognized = result.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()
            if (!recognized.isNullOrBlank()) {
                draft = recognized
                status = "已填入识别结果，请检查并修改后发送。"
            } else status = "没有识别到文字，可直接输入。"
        } else status = "语音识别已取消，可继续使用文字。"
    }

    DisposableEffect(context) {
        val engine = TextToSpeech(context) { result ->
            speakerReady = result == TextToSpeech.SUCCESS
        }
        speaker = engine
        onDispose { engine.stop(); engine.shutdown(); speaker = null; speakerReady = false }
    }

    LaunchedEffect(token, selectedPage) {
        val currentToken = token
        if (currentToken == null) { hudSnapshot = null; return@LaunchedEffect }
        try {
            val items = api.lifeItems(currentToken)
            val devices = api.pcDevices(currentToken)
            val tasks = items.count { it.kind == "task" && it.status == "open" }
            val schedules = items.count { it.kind == "schedule" && it.status == "planned" }
            val pc = if (devices.none { !it.revoked }) "未配对" else if (devices.any { it.online }) "在线" else "离线"
            hudSnapshot = "待办 $tasks 项 · 日程 $schedules 项 · PC $pc"
        } catch (_: Exception) { hudSnapshot = "任务与设备状态暂不可用" }
    }

    LaunchedEffect(Unit) {
        val saved = store.read()
        if (saved != null) {
            try {
                val profile = api.me(saved)
                val history = api.history(saved)
                token = saved
                account = profile
                messages = history
            } catch (error: ApiFailure) {
                if (error.status == 401) store.clear()
                status = if (error.status == 401) "登录已过期，请重新登录。" else error.message.orEmpty()
            } catch (error: Exception) {
                status = error.message ?: "暂时无法恢复登录，请稍后重试。"
            }
        }
        restoring = false
    }

    Column(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text("Dengvis", style = MaterialTheme.typography.headlineSmall)
        Text(if (isDebug) "本地调试 · 正式账号" else if (serverReady) "已配置 HTTPS 服务" else "发布版尚未配置 HTTPS 服务地址", style = MaterialTheme.typography.bodySmall)
        if (restoring) {
            Text("正在恢复登录…")
        } else if (token == null) {
            Text(if (registering) "注册账号" else "登录账号", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(
                value = email,
                onValueChange = { email = it },
                label = { Text("邮箱") },
                singleLine = true,
                enabled = !busy && serverReady,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = password,
                onValueChange = { password = it },
                label = { Text("密码（至少 12 个字符）") },
                visualTransformation = PasswordVisualTransformation(),
                singleLine = true,
                enabled = !busy && serverReady,
                modifier = Modifier.fillMaxWidth(),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    onClick = {
                        busy = true
                        status = ""
                        scope.launch {
                            try {
                                if (registering) api.register(email.trim(), password)
                                val session = api.login(email.trim(), password)
                                store.save(session.token)
                                val profile = api.me(session.token)
                                token = session.token
                                account = profile
                                password = ""
                                try {
                                    messages = api.history(session.token)
                                } catch (error: Exception) {
                                    status = error.message ?: "历史记录暂时无法读取。"
                                }
                            } catch (error: Exception) {
                                status = error.message ?: "账号操作失败，请重试。"
                            } finally {
                                busy = false
                            }
                        }
                    },
                    enabled = serverReady && !busy && email.isNotBlank() && password.length >= 12,
                ) { Text(if (registering) "注册并登录" else "登录") }
                Button(onClick = { registering = !registering; status = "" }, enabled = !busy && serverReady) {
                    Text(if (registering) "已有账号" else "创建账号")
                }
            }
        } else {
            Text(account?.email ?: "已登录", style = MaterialTheme.typography.titleMedium)
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(12.dp)) {
                    Text("状态 HUD · 对话${if (busy) "处理中" else "待机"}", style = MaterialTheme.typography.titleSmall)
                    Text(hudSnapshot ?: "正在读取任务与设备状态…", style = MaterialTheme.typography.bodySmall)
                }
            }
            Button(
                onClick = {
                    val currentToken = token ?: return@Button
                    busy = true
                    scope.launch {
                        try {
                            api.logout(currentToken)
                            store.clear()
                            token = null
                            account = null
                            messages = emptyList()
                            draft = ""
                            selectedPage = "home"
                            status = "已退出登录。"
                        } catch (error: ApiFailure) {
                            if (error.status == 401) {
                                store.clear()
                                token = null
                                account = null
                                messages = emptyList()
                                status = "登录已过期，请重新登录。"
                            } else status = error.message.orEmpty()
                        } catch (error: Exception) {
                            status = error.message ?: "退出失败，请重试。"
                        } finally {
                            busy = false
                        }
                    }
                },
                enabled = !busy,
            ) { Text("退出登录") }
            Row(modifier = Modifier.fillMaxWidth()) {
                listOf("home" to "首页", "life" to "任务", "study" to "学习", "chat" to "AI对话", "memory" to "我的").forEach { (page, label) ->
                    Box(modifier = Modifier.weight(1f).height(48.dp).clickable { selectedPage = page }, contentAlignment = Alignment.Center) {
                        Text(label, fontSize = 14.sp, maxLines = 1,
                            fontWeight = if (selectedPage == page) FontWeight.Bold else FontWeight.Normal,
                            color = if (selectedPage == page) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface)
                    }
                }
            }
            if (selectedPage == "home") {
                AccountHomeScreen(api, token!!, onOpenDayDemo = { selectedPage = "day" }, modifier = Modifier.weight(1f))
            } else if (selectedPage == "day") {
                AccountDayDemoScreen(api, token!!, account!!.id, onBack = { selectedPage = "home" }, modifier = Modifier.weight(1f))
            } else if (selectedPage == "life") {
                AccountLifeScreen(api, token!!, modifier = Modifier.weight(1f))
            } else if (selectedPage == "memory") {
                AccountMemoryScreen(api, token!!, modifier = Modifier.weight(1f))
            } else if (selectedPage == "study") {
                AccountStudyScreen(api, token!!, modifier = Modifier.weight(1f))
            } else {
            LazyColumn(modifier = Modifier.weight(1f).fillMaxWidth()) {
                items(messages) { item ->
                    Text("${if (item.role == "user") "我" else "Jarvis"}：${item.content}", modifier = Modifier.padding(vertical = 7.dp))
                    if (item.role == "assistant") Button(onClick = {
                        val engine = speaker
                        if (speakerReady && engine != null) {
                            engine.language = Locale.SIMPLIFIED_CHINESE
                            engine.speak(item.content, TextToSpeech.QUEUE_FLUSH, null, "jarvis-reply")
                        } else status = "语音播报不可用，文字回复仍可阅读。"
                    }) { Text("朗读") }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = draft,
                    onValueChange = { draft = it },
                    label = { Text("输入消息") },
                    enabled = !busy,
                    modifier = Modifier.weight(1f),
                )
                Button(
                    onClick = {
                        val currentToken = token ?: return@Button
                        val content = draft.trim()
                        if (content.isEmpty()) return@Button
                        busy = true
                        scope.launch {
                            try {
                                val reply = api.send(currentToken, content)
                                messages = messages + ChatMessage("user", content) + ChatMessage("assistant", reply)
                                draft = ""
                                status = ""
                            } catch (error: ApiFailure) {
                                if (error.status == 401) {
                                    store.clear()
                                    token = null
                                    account = null
                                    messages = emptyList()
                                    status = "登录已过期，请重新登录后发送。"
                                } else status = error.message.orEmpty()
                            } catch (error: Exception) {
                                status = error.message ?: "发送失败，请重试。"
                            } finally {
                                busy = false
                            }
                        }
                    },
                    enabled = !busy && draft.isNotBlank() && draft.length <= 4000,
                ) { Text("发送") }
                Button(onClick = {
                    try {
                        voiceLauncher.launch(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-CN")
                            putExtra(RecognizerIntent.EXTRA_PROMPT, "说完后可检查和修改文字")
                        })
                    } catch (_: ActivityNotFoundException) {
                        status = "设备没有可用的语音识别服务，请使用文字输入。"
                    }
                }, enabled = !busy) { Text("语音") }
            }
            Text("系统语音识别可能联网；识别文字会先供你检查和修改。聊天记录短期保留。", style = MaterialTheme.typography.bodySmall)
            }
        }
        if (status.isNotBlank()) Text(status, color = MaterialTheme.colorScheme.error)
    }
}

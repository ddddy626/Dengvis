package com.dengvis.prototype

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import org.json.JSONArray
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URI
import java.net.SocketTimeoutException
import java.net.URL

data class Account(val id: Long, val email: String)
data class AccountSession(val token: String, val expiresAt: String)
data class ChatMessage(val role: String, val content: String)
data class SavedItemRef(val kind: String, val id: Long)
data class LifePlan(val jobId: Long, val status: String, val items: List<LifeDraft>, val saved: List<SavedItemRef> = emptyList())
data class LifeDraft(val kind: String, val title: String, val dueAt: String? = null, val startsAt: String? = null, val endsAt: String? = null)
data class LifeSuggestion(val items: List<LifeDraft>, val questions: List<String>)
data class LifeSaved(val id: Long, val kind: String, val title: String, val status: String, val dueAt: String? = null, val startsAt: String? = null, val endsAt: String? = null)
data class LifeMorning(val date: String, val tasks: Int, val schedules: Int, val sleepStatus: String)
data class LifeJob(val id: Long, val status: String, val preview: String, val latestEvent: String?)
data class LifeJobEvent(val seq: Int, val summary: String)
data class PermissionGrant(val scope: String, val dataSource: String)
data class MemoryCandidate(val id: Long, val summary: String, val evidenceRef: String, val purpose: String, val expiresAt: String, val status: String)
data class PcDevice(val id: Long, val online: Boolean, val lastSeen: String?, val revoked: Boolean)
data class PairCode(val code: String, val expiresAt: String)
data class StudyExcerpt(val source: String, val page: Int, val text: String, val score: Double)
data class StudyJob(val id: Long, val query: String, val status: String, val modelName: String?, val error: String?, val elapsedMs: Int?, val excerpts: List<StudyExcerpt>)

class ApiFailure(val code: String, val status: Int, message: String) : Exception(message)

class JarvisApi(private val baseUrl: String, private val allowLocalHttp: Boolean) {
    suspend fun register(email: String, password: String): Account = withContext(Dispatchers.IO) {
        val result = request("POST", "/api/v1/auth/register", body = credentials(email, password))!!
        Account(result.getLong("id"), result.getString("email"))
    }

    suspend fun login(email: String, password: String): AccountSession = withContext(Dispatchers.IO) {
        val result = request("POST", "/api/v1/auth/login", body = credentials(email, password))!!
        AccountSession(result.getString("token"), result.getString("expiresAt"))
    }

    suspend fun me(token: String): Account = withContext(Dispatchers.IO) {
        val result = request("GET", "/api/v1/auth/me", token)!!
        Account(result.getLong("id"), result.getString("email"))
    }

    suspend fun logout(token: String) = withContext(Dispatchers.IO) {
        request("POST", "/api/v1/auth/logout", token)
    }

    suspend fun history(token: String): List<ChatMessage> = withContext(Dispatchers.IO) {
        val items = request("GET", "/api/v1/account/chat/history", token)!!.getJSONArray("messages")
        List(items.length()) { index ->
            val item = items.getJSONObject(index)
            ChatMessage(item.getString("role"), item.getString("content"))
        }
    }

    suspend fun send(token: String, message: String): String = withContext(Dispatchers.IO) {
        request("POST", "/api/v1/account/chat", token, JSONObject().put("message", message))!!.getString("reply")
    }

    suspend fun suggestLife(token: String, intent: String): LifeSuggestion = withContext(Dispatchers.IO) {
        val result = request("POST", "/api/v1/account/life/suggest", token, JSONObject().put("intent", intent))!!
        parseSuggestion(result)
    }

    suspend fun createLifePlan(token: String, intent: String, key: String, suggested: List<LifeDraft>? = null): LifePlan = withContext(Dispatchers.IO) {
        val body = JSONObject().put("intent", intent).put("idempotencyKey", key)
        suggested?.let { drafts ->
            val items = JSONArray()
            drafts.forEach { draft ->
                val item = JSONObject().put("kind", draft.kind).put("title", draft.title)
                draft.dueAt?.let { item.put("dueAt", it) }
                draft.startsAt?.let { item.put("startsAt", it) }
                draft.endsAt?.let { item.put("endsAt", it) }
                items.put(item)
            }
            body.put("items", items)
        }
        parsePlan(request("POST", "/api/v1/account/life/plans", token, body)!!)
    }

    suspend fun lifePlan(token: String, jobId: Long): LifePlan = withContext(Dispatchers.IO) {
        parsePlan(request("GET", "/api/v1/account/life/plans/$jobId", token)!!)
    }

    suspend fun editLifePlan(token: String, plan: LifePlan): LifePlan = withContext(Dispatchers.IO) {
        val items = JSONArray()
        plan.items.forEach { item ->
            val value = JSONObject().put("kind", item.kind).put("title", item.title)
            item.dueAt?.let { value.put("dueAt", it) }
            item.startsAt?.let { value.put("startsAt", it) }
            item.endsAt?.let { value.put("endsAt", it) }
            items.put(value)
        }
        parsePlan(request("PUT", "/api/v1/account/life/plans/${plan.jobId}", token, JSONObject().put("items", items))!!)
    }

    suspend fun decideLifePlan(token: String, jobId: Long, allow: Boolean, rememberScope: Boolean = false): LifePlan = withContext(Dispatchers.IO) {
        parsePlan(request("POST", "/api/v1/account/life/plans/$jobId/decision", token,
            JSONObject().put("decision", if (!allow) "deny" else if (rememberScope) "allow_scope" else "allow_once"))!!)
    }

    suspend fun permissions(token: String): List<PermissionGrant> = withContext(Dispatchers.IO) {
        val array = requestArray("/api/v1/account/permissions", token)
        List(array.length()) { index ->
            val item = array.getJSONObject(index)
            PermissionGrant(item.getString("scope"), item.getString("dataSource"))
        }
    }

    suspend fun revokePermission(token: String, scope: String): Boolean = withContext(Dispatchers.IO) {
        request("POST", "/api/v1/account/permissions/revoke", token, JSONObject().put("scope", scope))!!
            .getBoolean("revoked")
    }

    suspend fun lifeItems(token: String): List<LifeSaved> = withContext(Dispatchers.IO) {
        val result = request("GET", "/api/v1/account/life/items", token)!!
        val output = mutableListOf<LifeSaved>()
        for (kind in listOf("tasks", "schedules")) {
            val array = result.getJSONArray(kind)
            for (index in 0 until array.length()) {
                val item = array.getJSONObject(index)
                output.add(LifeSaved(item.getLong("id"), if (kind == "tasks") "task" else "schedule",
                    item.getString("title"), item.getString("status"), item.optStringOrNull("dueAt"),
                    item.optStringOrNull("startsAt"), item.optStringOrNull("endsAt")))
            }
        }
        output
    }

    suspend fun updateLifeItem(token: String, item: LifeSaved, title: String, status: String): Unit = withContext(Dispatchers.IO) {
        val body = JSONObject().put("title", title).put("status", status)
        item.dueAt?.let { body.put("dueAt", it) }
        item.startsAt?.let { body.put("startsAt", it) }
        item.endsAt?.let { body.put("endsAt", it) }
        request("PUT", "/api/v1/account/life/items/${item.kind}/${item.id}", token, body)
    }

    suspend fun morning(token: String, date: String): LifeMorning = withContext(Dispatchers.IO) {
        val result = request("GET", "/api/v1/account/life/morning?date=$date", token)!!
        val tasks = result.getJSONArray("tasks")
        val schedules = result.getJSONArray("schedules")
        LifeMorning(result.getString("date"),
            (0 until tasks.length()).count { tasks.getJSONObject(it).optString("status") == "open" },
            (0 until schedules.length()).count { schedules.getJSONObject(it).optString("status") == "planned" },
            result.getJSONObject("sleep").getString("status"))
    }

    suspend fun lifeJobs(token: String): List<LifeJob> = withContext(Dispatchers.IO) {
        val array = requestArray("/api/v1/account/life/jobs", token)
        List(array.length()) { index ->
            val item = array.getJSONObject(index)
            LifeJob(item.getLong("jobId"), item.getString("status"), item.getString("preview"), item.optStringOrNull("latestEvent"))
        }
    }

    suspend fun lifeJobEvents(token: String, jobId: Long): List<LifeJobEvent> = withContext(Dispatchers.IO) {
        val array = requestArray("/api/v1/account/life/jobs/$jobId/events", token)
        List(array.length()) { index ->
            val item = array.getJSONObject(index)
            LifeJobEvent(item.getInt("seq"), item.getString("summary"))
        }
    }

    suspend fun memoryCandidates(token: String): List<MemoryCandidate> = withContext(Dispatchers.IO) {
        val array = requestArray("/api/v1/account/memory/candidates", token)
        List(array.length()) { index ->
            val item = array.getJSONObject(index)
            MemoryCandidate(item.getLong("id"), item.getString("summary"), item.getString("evidenceRef"),
                item.getString("purpose"), item.getString("expiresAt"), item.getString("status"))
        }
    }

    suspend fun createMemoryCandidate(token: String, summary: String, purpose: String, expiresAt: String): Unit = withContext(Dispatchers.IO) {
        request("POST", "/api/v1/account/memory/candidates", token, JSONObject()
            .put("summary", summary).put("evidenceRef", "user_explicit:android")
            .put("purpose", purpose).put("expiresAt", expiresAt))
    }

    suspend fun editMemoryCandidate(token: String, item: MemoryCandidate): Unit = withContext(Dispatchers.IO) {
        request("PUT", "/api/v1/account/memory/candidates/${item.id}", token, JSONObject()
            .put("summary", item.summary).put("purpose", item.purpose).put("expiresAt", item.expiresAt))
    }

    suspend fun decideMemoryCandidate(token: String, id: Long, allow: Boolean): Unit = withContext(Dispatchers.IO) {
        request("POST", "/api/v1/account/memory/candidates/$id/decision", token,
            JSONObject().put("decision", if (allow) "confirm" else "reject"))
    }

    suspend fun revokeMemoryCandidate(token: String, id: Long): Unit = withContext(Dispatchers.IO) {
        request("POST", "/api/v1/account/memory/candidates/$id/revoke", token)
    }

    suspend fun deleteMemoryCandidate(token: String, id: Long): Unit = withContext(Dispatchers.IO) {
        request("DELETE", "/api/v1/account/memory/candidates/$id", token)
    }

    suspend fun createPcPairCode(token: String): PairCode = withContext(Dispatchers.IO) {
        val result = request("POST", "/api/v1/account/pc/pair", token)!!
        PairCode(result.getString("code"), result.getString("expiresAt"))
    }

    suspend fun pcDevices(token: String): List<PcDevice> = withContext(Dispatchers.IO) {
        val array = requestArray("/api/v1/account/pc/devices", token)
        List(array.length()) { index ->
            val item = array.getJSONObject(index)
            PcDevice(item.getLong("deviceId"), item.getBoolean("online"), item.optStringOrNull("lastSeen"), item.getBoolean("revoked"))
        }
    }

    suspend fun revokePcDevice(token: String, id: Long): Unit = withContext(Dispatchers.IO) {
        request("POST", "/api/v1/account/pc/devices/$id/revoke", token)
    }

    suspend fun createStudyJob(token: String, query: String, key: String): StudyJob = withContext(Dispatchers.IO) {
        parseStudyJob(request("POST", "/api/v1/account/pc/study", token,
            JSONObject().put("query", query).put("idempotencyKey", key))!!)
    }

    suspend fun studyJobs(token: String): List<StudyJob> = withContext(Dispatchers.IO) {
        val array = requestArray("/api/v1/account/pc/study", token)
        List(array.length()) { index -> parseStudyJob(array.getJSONObject(index)) }
    }

    suspend fun retryStudyJob(token: String, id: Long): StudyJob = withContext(Dispatchers.IO) {
        parseStudyJob(request("POST", "/api/v1/account/pc/study/$id/retry", token)!!)
    }

    suspend fun studyDraft(token: String, id: Long): LifePlan = withContext(Dispatchers.IO) {
        parsePlan(request("POST", "/api/v1/account/pc/study/$id/draft", token)!!)
    }

    suspend fun studySuggest(token: String, id: Long): LifeSuggestion = withContext(Dispatchers.IO) {
        parseSuggestion(request("POST", "/api/v1/account/pc/study/$id/suggest", token)!!)
    }

    private fun parseSuggestion(value: JSONObject): LifeSuggestion {
        val items = value.getJSONArray("items")
        val questions = value.optJSONArray("questions") ?: JSONArray()
        return LifeSuggestion(List(items.length()) { index -> parseDraft(items.getJSONObject(index)) },
            List(questions.length()) { index -> questions.getString(index) })
    }

    private fun parseStudyJob(value: JSONObject): StudyJob {
        val result = value.optJSONObject("result")
        val excerpts = result?.optJSONArray("excerpts")
        return StudyJob(value.getLong("jobId"), value.getString("query"), value.getString("status"),
            result?.optStringOrNull("modelName"), result?.optStringOrNull("error"),
            result?.optInt("elapsedMs"), if (excerpts == null) emptyList() else List(excerpts.length()) { index ->
                val item = excerpts.getJSONObject(index)
                StudyExcerpt(item.getString("source"), item.getInt("page"), item.getString("text"), item.getDouble("score"))
            })
    }

    private fun checkedOrigin(): String {
        val origin = baseUrl.trim().trimEnd('/')
        val uri = runCatching { URI(origin) }.getOrNull()
        val host = uri?.host?.lowercase()
        val cleanOrigin = host != null && uri?.userInfo == null && uri?.path.isNullOrEmpty() &&
            uri?.query == null && uri?.fragment == null
        val secure = cleanOrigin && uri?.scheme.equals("https", ignoreCase = true)
        val localHttp = cleanOrigin && allowLocalHttp && uri?.scheme.equals("http", ignoreCase = true) &&
            host in listOf("10.0.2.2", "127.0.0.1", "localhost")
        if (!secure && !localHttp) {
            throw ApiFailure("INSECURE_SERVER", 0, "请使用 HTTPS 服务地址；调试版仅允许本机地址。")
        }
        return origin
    }

    private fun requestArray(path: String, token: String): JSONArray {
        val origin = checkedOrigin()
        val connection = (URL("$origin$path").openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            instanceFollowRedirects = false
            connectTimeout = 8_000
            readTimeout = 40_000
            setRequestProperty("Authorization", "Bearer $token")
        }
        try {
            val status = connection.responseCode
            val content = (if (status in 200..299) connection.inputStream else connection.errorStream)
                ?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (status !in 200..299) {
                val error = runCatching { JSONObject(content) }.getOrNull()
                throw ApiFailure(error?.optString("code") ?: "HTTP_ERROR", status,
                    error?.optString("message").orEmpty().ifBlank { "读取失败（HTTP $status）。" })
            }
            return JSONArray(content)
        } finally { connection.disconnect() }
    }

    suspend fun cancelLifeJob(token: String, jobId: Long): Unit = withContext(Dispatchers.IO) {
        request("POST", "/api/v1/account/life/jobs/$jobId/cancel", token)
    }

    private fun parsePlan(value: JSONObject): LifePlan {
        val array = value.getJSONArray("items")
        val saved = value.optJSONArray("saved") ?: JSONArray()
        return LifePlan(value.getLong("jobId"), value.getString("status"), List(array.length()) { index ->
            parseDraft(array.getJSONObject(index))
        }, List(saved.length()) { index ->
            val item = saved.getJSONObject(index)
            SavedItemRef(item.getString("kind"), item.getLong("id"))
        })
    }

    private fun parseDraft(item: JSONObject): LifeDraft =
        LifeDraft(item.getString("kind"), item.getString("title"), item.optStringOrNull("dueAt"),
            item.optStringOrNull("startsAt"), item.optStringOrNull("endsAt"))

    private fun JSONObject.optStringOrNull(key: String): String? =
        if (isNull(key)) null else optString(key).takeIf { it.isNotBlank() }

    private fun credentials(email: String, password: String): JSONObject =
        JSONObject().put("email", email).put("password", password)

    private fun request(method: String, path: String, token: String? = null, body: JSONObject? = null): JSONObject? {
        val origin = checkedOrigin()
        val connection = (URL("$origin$path").openConnection() as HttpURLConnection).apply {
            requestMethod = method
            instanceFollowRedirects = false
            connectTimeout = 8_000
            readTimeout = 40_000
            setRequestProperty("Accept", "application/json")
            if (token != null) setRequestProperty("Authorization", "Bearer $token")
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
            }
        }
        try {
            if (body != null) connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            val status = connection.responseCode
            val content = (if (status in 200..299) connection.inputStream else connection.errorStream)
                ?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (status !in 200..299) {
                val error = runCatching { JSONObject(content) }.getOrNull()
                throw ApiFailure(
                    error?.optString("code").orEmpty().ifBlank { "HTTP_ERROR" },
                    status,
                    error?.optString("message").orEmpty().ifBlank { "服务请求失败（HTTP $status）" },
                )
            }
            if (status == 204) return null
            return runCatching { JSONObject(content) }.getOrElse {
                throw ApiFailure("BAD_RESPONSE", status, "服务返回的数据无法读取。")
            }
        } catch (_: SocketTimeoutException) {
            throw ApiFailure("NETWORK_TIMEOUT", 0, "连接超时，请检查网络后重试。")
        } catch (_: IOException) {
            throw ApiFailure("NETWORK_UNAVAILABLE", 0, "无法连接服务，请检查地址和网络。")
        } finally {
            connection.disconnect()
        }
    }
}

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

val configuredApiBaseUrl = providers.gradleProperty("DENGVIS_API_BASE_URL").orNull.orEmpty().trimEnd('/')
require(configuredApiBaseUrl.isEmpty() || Regex("^https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?$").matches(configuredApiBaseUrl)) {
    "DENGVIS_API_BASE_URL must be an HTTPS origin without a path."
}

android {
    namespace = "com.dengvis.prototype"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.dengvis.prototype"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
        resValue("string", "api_base_url", configuredApiBaseUrl)
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
    }
}

dependencies {
    implementation("androidx.activity:activity-compose:1.11.0")
    implementation("androidx.compose.ui:ui:1.9.1")
    implementation("androidx.compose.material3:material3:1.3.2")
}

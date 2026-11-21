plugins {
    id("com.android.application")
}

android {
    namespace = "com.worn.glasses"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.worn.glasses"
        minSdk = 26
        targetSdk = 28 // the M6 runs Android 9 (API 28)
        versionCode = 1
        versionName = "0.1"
        val api = (project.findProperty("worn.api") as String?) ?: "http://127.0.0.1:8000"
        buildConfigField("String", "DEFAULT_API", "\"$api\"")
    }
    buildFeatures { buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }
    lint { abortOnError = false; checkReleaseBuilds = false }
}
// No dependencies on purpose: plain Android framework only, so the build works offline once the SDK is cached.

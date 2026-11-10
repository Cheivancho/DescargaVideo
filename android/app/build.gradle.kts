import java.util.Properties
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

val ytdlpAndroid = "0.18.1"

android {
    namespace = "com.cheivancho.descargador"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.cheivancho.descargador"
        minSdk = 29 // Android 10: guardar en Descargas sin permisos de almacenamiento
        targetSdk = 36
        versionCode = (project.findProperty("appVersionCode") as String?)?.toInt() ?: 4
        versionName = (project.findProperty("appVersionName") as String?) ?: "0.2.0"
        ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a", "x86_64") }
    }

    splits {
        abi {
            isEnable = true
            reset()
            include("arm64-v8a", "armeabi-v7a", "x86_64")
            isUniversalApk = true
        }
    }

    signingConfigs {
        val props = rootProject.file("keystore.properties")
        if (props.exists()) {
            create("release") {
                val p = Properties().apply { props.inputStream().use { load(it) } }
                storeFile = rootProject.file(p.getProperty("storeFile"))
                storePassword = p.getProperty("storePassword")
                keyAlias = p.getProperty("keyAlias")
                keyPassword = p.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfigs.findByName("release")?.let { signingConfig = it }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures { compose = true }
    packaging {
        jniLibs { useLegacyPackaging = true } // equivale a extractNativeLibs=true (lo exige youtubedl-android)
    }
}

kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2025.12.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose:1.11.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.4")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.4")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.11.0")

    implementation("io.github.junkfood02.youtubedl-android:library:$ytdlpAndroid")
    implementation("io.github.junkfood02.youtubedl-android:ffmpeg:$ytdlpAndroid")
}

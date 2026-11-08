plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// sherpa-onnx (offline speech recognition) is published as an .aar on GitHub,
// not on Maven Central, so fetch it once into app/libs.
val sherpaVersion = "2.0.1"
val sherpaAar = file("libs/sherpa-onnx-$sherpaVersion.aar")
if (!sherpaAar.exists()) {
    sherpaAar.parentFile.mkdirs()
    val tmp = File(sherpaAar.path + ".part")
    uri("https://github.com/k2-fsa/sherpa-onnx/releases/download/v$sherpaVersion/sherpa-onnx-$sherpaVersion.aar")
        .toURL().openStream().use { input -> tmp.outputStream().use { input.copyTo(it) } }
    tmp.renameTo(sherpaAar)
}

android {
    namespace = "sk.hlas.dictation"
    compileSdk = 35

    defaultConfig {
        applicationId = "sk.hlas.dictation"
        minSdk = 26
        targetSdk = 35
        versionCode = 2
        versionName = "0.2.0"
        ndk {
            abiFilters += listOf("arm64-v8a")  // the 1.3 GB models need a modern 64-bit phone anyway
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // Signed with the debug key so CI can produce an installable APK.
            // Use your own keystore for a Play Store release.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    packaging {
        resources {
            excludes += setOf("META-INF/*.kotlin_module", "META-INF/DEPENDENCIES", "META-INF/LICENSE*",
                "META-INF/NOTICE*", "META-INF/versions/9/OSGI-INF/MANIFEST.MF")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

// Optional end-to-end test of the offline engine on this computer:
//   SHERPA_JNI_DIR=<linux sherpa-onnx jni lib dir> HLAS_MODELS_DIR=<models dir> HLAS_TEST_WAVS=<dir> ./gradlew testDebugUnitTest
tasks.withType<Test>().configureEach {
    System.getenv("SHERPA_JNI_DIR")?.let { systemProperty("java.library.path", it) }
    listOf("HLAS_MODELS_DIR", "HLAS_TEST_WAVS", "HLAS_DOWNLOAD_TEST").forEach { k -> System.getenv(k)?.let { environment(k, it) } }
    testLogging { showStandardStreams = true }
}

dependencies {
    implementation(files("libs/sherpa-onnx-$sherpaVersion.aar"))  // offline speech models
    implementation("com.anthropic:anthropic-java:3.6.0")   // optional paid Claude cleanup
    implementation("com.squareup.okhttp3:okhttp:4.12.0")    // speech-to-text uploads
    testImplementation("junit:junit:4.13.2")
}

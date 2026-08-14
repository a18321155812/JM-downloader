plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.chaquo.python")
}

// 临时：换 build 目录绕过旧文件锁定（后续可删除此配置）
layout.buildDirectory = file("build_v222")

android {
    namespace = "com.jmcomic.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.jmcomic.app"
        minSdk = 26
        targetSdk = 35
        versionCode = 22
        versionName = "2.0.22"

        // Chaquopy 需要指定 ABI
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    // 输出文件名带版本号（避免旧文件被占用时无法覆盖）
    applicationVariants.all {
        outputs.all {
            (this as com.android.build.gradle.internal.api.BaseVariantOutputImpl)
                .outputFileName = "JMDownloader_${versionName}.apk"
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    kotlinOptions {
        jvmTarget = "11"
    }
    buildFeatures {
        compose = true
    }
}

// Chaquopy：内嵌 Python 运行 jmcomic
chaquopy {
    defaultConfig {
        version = "3.13"
        // 本机 Python 3.13（与 App 内嵌版本一致）
        // 通过环境变量 CHAQUOPY_PYTHON 指定本机 python.exe，未设置时回退到 PATH 中的 python
        buildPython(System.getenv("CHAQUOPY_PYTHON") ?: "python")
        pip {
            // jmcomic 依赖 curl_cffi（安卓不可用），用 requests 替代，故 --no-deps 手动补齐全部依赖
            options("--no-deps")
            // jmcomic 本体
            install("jmcomic")
            install("commonx")
            // requests 及其依赖
            install("requests")
            install("urllib3")
            install("certifi")
            install("charset-normalizer")
            install("idna")
            // 图片处理 / 加密（pillow 的 Android 版依赖 chaquopy-libjpeg）
            install("pillow")
            install("chaquopy-libjpeg")
            install("pycryptodome")
            install("PyYAML")
            // flask 及其依赖
            install("flask")
            install("werkzeug")
            install("jinja2")
            install("click")
            install("itsdangerous")
            install("blinker")
            install("markupsafe")
            // PDF 转换（jmcomic 的 img2pdf 插件运行时需要，img2pdf 依赖 lxml）
            install("img2pdf")
            install("lxml")
            // 加密 ZIP / 7z（pyzipper 纯 Python；py7zr 支持 7z 格式）
            install("pyzipper")
            install("py7zr")
        }
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("io.coil-kt:coil-compose:2.7.0")
}

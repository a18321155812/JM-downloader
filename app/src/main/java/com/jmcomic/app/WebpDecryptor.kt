package com.jmcomic.app

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Rect
import java.io.FileOutputStream
import java.security.MessageDigest

/**
 * WebP 图片解密器
 * =================
 * 手机上 Chaquopy 的 Pillow 不支持 WebP（缺 libwebp），因此用 Android 原生解码：
 *   1. BitmapFactory 解码 webp 数据（Android 系统原生支持）
 *   2. 移植 jmcomic 的 scramble 分段重排解密算法
 *   3. 重新编码为 WebP 保存（保持原扩展名一致）
 */
object WebpDecryptor {

    private const val SCRAMBLE_268850 = 268850
    private const val SCRAMBLE_421926 = 421926

    /**
     * 解码 → 解密 → 保存 WebP
     * @param webpData 原始 webp 字节（加密/混淆状态）
     * @param scrambleId photo 的 scramble_id
     * @param aid 本子 ID
     * @param filename 图片文件名（如 00001.webp）
     * @param savePath 保存路径（保持 .webp 扩展名）
     */
    @JvmStatic
    fun decryptAndSave(
        webpData: ByteArray,
        scrambleId: Int,
        aid: String,
        filename: String,
        savePath: String,
    ): Boolean {
        try {
            val bitmap = BitmapFactory.decodeByteArray(webpData, 0, webpData.size)
                ?: return false
            // 与 jmcomic of_file_name(url, True) 一致：文件名必须去掉扩展名，否则分割数算错
            val baseName = filename.substringBeforeLast('.')
            val num = getNum(scrambleId, aid.toIntOrNull() ?: 0, baseName)
            val decoded = if (num > 0) scrambleDecode(bitmap, num) else bitmap
            FileOutputStream(savePath).use { out ->
                // 保存为 PNG：Pillow 在安卓支持 PNG（zlib），后续 PDF 转换插件才能读取
                decoded.compress(Bitmap.CompressFormat.PNG, 100, out)
            }
            if (decoded !== bitmap) decoded.recycle()
            bitmap.recycle()
            return true
        } catch (e: Exception) {
            return false
        }
    }

    /** 图片分割数（与 jmcomic jm_toolkit.get_num 算法一致） */
    private fun getNum(scrambleId: Int, aid: Int, filename: String): Int {
        if (aid < scrambleId) return 0
        if (aid < SCRAMBLE_268850) return 10
        val x = if (aid < SCRAMBLE_421926) 10 else 8
        val s = "$aid$filename"
        val digest = MessageDigest.getInstance("MD5").digest(s.toByteArray())
        // 注意：Byte 是带符号的，必须掩码 0xFF 再格式化，否则负数会输出 8 位导致取错字符
        val hex = digest.joinToString("") { "%02x".format(it.toInt() and 0xFF) }
        val num = hex.last().code % x
        return num * 2 + 2
    }

    /** scramble 解密：按行分段重排（与 jmcomic decode_and_save 一致） */
    private fun scrambleDecode(src: Bitmap, num: Int): Bitmap {
        val w = src.width
        val h = src.height
        val decoded = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(decoded)
        val paint = Paint()
        val moveBase = Math.floorDiv(h, num)
        val over = h % num
        for (i in 0 until num) {
            var move = moveBase
            var ySrc = h - (moveBase * (i + 1)) - over
            var yDst = moveBase * i
            if (i == 0) {
                move += over
            } else {
                yDst += over
            }
            canvas.drawBitmap(
                src,
                Rect(0, ySrc, w, ySrc + move),
                Rect(0, yDst, w, yDst + move),
                paint
            )
        }
        return decoded
    }
}

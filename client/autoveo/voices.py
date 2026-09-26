"""30 giọng đọc có sẵn của Veo (dùng cho chế độ Đồng bộ nhân vật). Tên gửi đi là chữ thường; mô tả để người dùng chọn."""
from __future__ import annotations

VOICE_LABELS = [
    "Achernar - Nữ, giọng mềm, cao độ cao",
    "Achird - Nam, giọng thân thiện, cao độ trung bình",
    "Algenib - Nam, giọng khàn/đục, cao độ thấp",
    "Algieba - Nam, giọng thoải mái, cao độ trung bình-thấp",
    "Alnilam - Nam, giọng chắc, cao độ trung bình-thấp",
    "Aoede - Nữ, giọng nhẹ thoáng, cao độ trung bình",
    "Autonoe - Nữ, giọng sáng, cao độ trung bình",
    "Callirrhoe - Nữ, giọng thoải mái, cao độ trung bình",
    "Charon - Nam, giọng cung cấp thông tin, cao độ thấp hơn",
    "Despina - Nữ, giọng mượt, cao độ trung bình",
    "Enceladus - Nam, giọng thoảng hơi, cao độ thấp hơn",
    "Erinome - Nữ, giọng rõ ràng, cao độ trung bình",
    "Fenrir - Nam, giọng hào hứng, tông trẻ hơn",
    "Gacrux - Nữ, giọng trưởng thành, cao độ trung bình",
    "Iapetus - Nam, giọng rõ ràng, cao độ trung bình-thấp",
    "Kore - Nữ, giọng chắc, cao độ trung bình",
    "Laomedeia - Nữ, giọng vui tươi, cao độ trung bình-cao",
    "Leda - Nữ, giọng trẻ trung, cao độ trung bình-cao",
    "Orus - Nam, giọng chắc, cao độ trung bình-thấp",
    "Puck - Nam, giọng vui tươi, cao độ trung bình",
    "Pulcherrima - Phi giới tính, giọng trực diện, cao độ trung bình-cao",
    "Rasalgethi - Nam, giọng mang tính cung cấp thông tin, cao độ trung bình",
    "Sadachbia - Nam, giọng sinh động, cao độ thấp",
    "Sadaltager - Nam, giọng hiểu biết, cao độ trung bình",
    "Schedar - Nam, giọng đều, cao độ trung bình-thấp",
    "Sulafat - Nữ, giọng ấm, cao độ trung bình",
    "Umbriel - Nam, giọng mượt, cao độ thấp hơn",
    "Vindemiatrix - Nữ, giọng dịu dàng, cao độ trung bình",
    "Zephyr - Nữ, giọng sáng, cao độ trung bình-cao",
    "Zubenelgenubi - Nam, giọng tự nhiên/thân mật, cao độ trung bình-thấp",
]

VOICES: list[tuple[str, str]] = [(t.split(" - ")[0].lower(), t) for t in VOICE_LABELS]   # (mã gửi đi, nhãn hiển thị)
VOICE_CODES = {code for code, _ in VOICES}

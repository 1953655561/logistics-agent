"""编码与名录表（小样本，够跑评测；生产环境应从海关税则/监管条件库加载）。"""

# ISO 4217 现行代码（含常用记账/离岸代码）。
# v1.5 起从 18 个常用码扩到全量：校验合同/发票币制合法性前必须先扩表，
# 否则 SDG（苏丹镑）这类合法代码会被误判成非法。
CURRENCIES = {
    "AED", "AFN", "ALL", "AMD", "ANG", "AOA", "ARS", "AUD", "AWG", "AZN",
    "BAM", "BBD", "BDT", "BGN", "BHD", "BIF", "BMD", "BND", "BOB", "BOV",
    "BRL", "BSD", "BTN", "BWP", "BYN", "BZD", "CAD", "CDF", "CHE", "CHF",
    "CHW", "CLF", "CLP", "CNY", "CNH", "COP", "COU", "CRC", "CUC", "CUP",
    "CVE", "CZK", "DJF", "DKK", "DOP", "DZD", "EGP", "ERN", "ETB", "EUR",
    "FJD", "FKP", "GBP", "GEL", "GHS", "GIP", "GMD", "GNF", "GTQ", "GYD",
    "HKD", "HNL", "HRK", "HTG", "HUF", "IDR", "ILS", "INR", "IQD", "IRR",
    "ISK", "JMD", "JOD", "JPY", "KES", "KGS", "KHR", "KMF", "KPW", "KRW",
    "KWD", "KYD", "KZT", "LAK", "LBP", "LKR", "LRD", "LSL", "LYD", "MAD",
    "MDL", "MGA", "MKD", "MMK", "MNT", "MOP", "MRU", "MUR", "MVR", "MWK",
    "MXN", "MXV", "MYR", "MZN", "NAD", "NGN", "NIO", "NOK", "NPR", "NZD",
    "OMR", "PAB", "PEN", "PGK", "PHP", "PKR", "PLN", "PYG", "QAR", "RON",
    "RSD", "RUB", "RWF", "SAR", "SBD", "SCR", "SDG", "SEK", "SGD", "SHP",
    "SLE", "SOS", "SRD", "SSP", "STN", "SVC", "SYP", "SZL", "THB", "TJS",
    "TMT", "TND", "TOP", "TRY", "TTD", "TWD", "TZS", "UAH", "UGX", "USD",
    "USN", "UYI", "UYU", "UYW", "UZS", "VED", "VES", "VND", "VUV", "WST",
    "XAF", "XCD", "XOF", "XPF", "YER", "ZAR", "ZMW", "ZWL",
}

# Incoterms 2020 十一种；L2-19 只认标准 3 字代码，避免 "OB"/"FOpB" 这类脏值静默通过。
INCOTERMS = {"EXW", "FCA", "FAS", "FOB", "CFR", "CIF",
             "CPT", "CIP", "DAP", "DPU", "DDP"}

COUNTRIES = {
    "CN", "US", "JP", "KR", "DE", "VN", "TH", "MY", "SG", "AU", "IT",
    "FR", "GB", "IN", "ID", "PH", "BR", "RU", "TW", "HK", "NL", "ES",
    "CA", "MX", "TR", "PL", "AE", "SA", "ZA", "NZ", "CL", "AR", "SE",
    "DK", "BE", "AT", "CH", "PT", "GR", "IE", "FI", "NO", "CZ", "HU",
    "RO", "UA", "EG", "NG", "KE", "PK", "BD", "LK", "MM", "KH", "LA", "MN",
}

# 包装种类里"应当有件数"的
PALLET_TYPES = {"托盘", "pallet", "木托", "栈板"}

# 需要 3C 的常见 6 位编码（玩具、小家电、灯具等）
CERT_REQUIRED_HS6 = {
    "950300", "950691", "850940", "851660", "851679", "940510", "940520",
    "950632", "871500", "392490", "691110", "732111",
}

# 禁止/限制进口：按 4 位编码前缀 + 关键词
PROHIBITED_HS4 = {
    "0508",  # 珊瑚等
    "0506",  # 骨、角等
    "2618", "2619",  # 矿渣
    "7204",  # 废钢铁
    "2525",  # 石棉制品
    "8548",  # 废电池等
}
PROHIBITED_KEYWORDS = {"固体废物", "固废", "旧机电", "旧设备", "洋垃圾", "濒危"}

# 双反税目（示意，生产应从公告库加载）
DUAL_ANTI_HS6 = {"721049", "730630", "400110", "290511", "390760"}

# 食品类 2 位章
FOOD_HS2 = {
    "02", "03", "04", "07", "08", "09", "10", "11", "12",
    "16", "17", "18", "19", "20", "21", "22",
}

# 贸易方式 ↔ 允许的征免性质
TRADE_MODE_EXEMPTION = {
    "一般贸易": {"照章征税", "一般征税"},
    "来料加工": {"来料加工", "免税"},
    "进料对口": {"进料加工", "免税"},
    "进料非对口": {"进料加工", "免税"},
}

"""
credentials.py — Mars Space tizimidagi o'quvchilar ma'lumotlari.

Key: Mars ID (str), Value: {name, password, group}
"""

MARS_CREDENTIALS: dict[str, dict] = {
    # ── nF-2506 ──────────────────────────────────────────────────────────────
    "1342455": {"name": "Ahmedov Abdulaziz",         "password": "20614", "group": "nF-2506"},
    "1332194": {"name": "Gayratov Abduvoris",        "password": "50841", "group": "nF-2506"},
    "1320801": {"name": "Hamidjonov Mahmudjon",      "password": "98135", "group": "nF-2506"},
    "1336522": {"name": "Sodiqov Firdavs",           "password": "12580", "group": "nF-2506"},
    "1319438": {"name": "Mirzoxidova Ziyoda",        "password": "70243", "group": "nF-2506"},
    "1318331": {"name": "Ahadullayev Salohiddin",    "password": "82950", "group": "nF-2506"},
    "1317869": {"name": "Nigmatullayev Bahtiyor",    "password": "40269", "group": "nF-2506"},
    "1325049": {"name": "Abdusattorov Bobur",        "password": "02647", "group": "nF-2506"},
    "1217408": {"name": "Nabiyev Abduvohid",         "password": "13672", "group": "nF-2506"},
    "1502473": {"name": "Abdialimov Asadbek",        "password": "82901", "group": "nF-2506"},
    "1219506": {"name": "Fahriddinova Aziza",        "password": "35047", "group": "nF-2506"},
    "1306073": {"name": "Yusupov Ismoil",            "password": "21680", "group": "nF-2506"},
    # ── nF-2694 ──────────────────────────────────────────────────────────────
    "1371234": {"name": "Abduqahhorov Abdusamad",    "password": "91057", "group": "nF-2694"},
    "1371874": {"name": "Boxodirov Sayfulloh",       "password": "03579", "group": "nF-2694"},
    "1373710": {"name": "Hidoyatov Komron",          "password": "15479", "group": "nF-2694"},
    "1375634": {"name": "Gofurov Muhammadamin",      "password": "07652", "group": "nF-2694"},
    "1370247": {"name": "Shavkatov Javohir",         "password": "38675", "group": "nF-2694"},
    "1367744": {"name": "Umarov Abdulloh",           "password": "14059", "group": "nF-2694"},
    "1309880": {"name": "Zokirjonov Zokirjon",       "password": "78691", "group": "nF-2694"},
    # ── nF-2749 ──────────────────────────────────────────────────────────────
    "1385621": {"name": "Abdumanoppov Azamat",       "password": "71092", "group": "nF-2749"},
    "1385732": {"name": "Abubakirov Mirlan",         "password": "19460", "group": "nF-2749"},
    "1386302": {"name": "Azimbergenov Qobiljon",     "password": "41862", "group": "nF-2749"},
    "1385856": {"name": "Hayrullayev Bahodir",       "password": "79835", "group": "nF-2749"},
    "1387899": {"name": "Mannonov Behruz",           "password": "93621", "group": "nF-2749"},
    "1386347": {"name": "Shavkatov Davron",          "password": "62875", "group": "nF-2749"},
    "1386295": {"name": "Tohirov Xojiakbar",         "password": "95764", "group": "nF-2749"},
    "1348530": {"name": "Bohodirov Odil",            "password": "03419", "group": "nF-2749"},
    "1412988": {"name": "Lutfullaev Oybek",          "password": "15370", "group": "nF-2749"},
    "1343213": {"name": "Malikov Mansur",            "password": "76908", "group": "nF-2749"},
    # ── nF-2803 ──────────────────────────────────────────────────────────────
    "1403768": {"name": "Fatxullayev Bobur",         "password": "72504", "group": "nF-2803"},
    "1396213": {"name": "Murodov Ayub",              "password": "53706", "group": "nF-2803"},
    "1407190": {"name": "Kabiljanova Sohiba",        "password": "51690", "group": "nF-2803"},
    "1402813": {"name": "Tohirjonov Bahrom",         "password": "51048", "group": "nF-2803"},
    "1275699": {"name": "Tohirov Hayriddin",         "password": "21876", "group": "nF-2803"},
    "1331321": {"name": "Allomurodov Azizbek",       "password": "41257", "group": "nF-2803"},
    "1343240": {"name": "Xudoynazarov Behruz",       "password": "08195", "group": "nF-2803"},
    # ── nF-2941 ──────────────────────────────────────────────────────────────
    "1423453": {"name": "Assatillayev Abdulloh",      "password": "61795", "group": "nF-2941"},
    "1420940": {"name": "Baxtiyorov Sunnatilla",      "password": "23986", "group": "nF-2941"},
    "1429361": {"name": "Bohodirov Humoyun",          "password": "47180", "group": "nF-2941"},
    "1422103": {"name": "Ismatullayev Dinislom",      "password": "15842", "group": "nF-2941"},
    "1427353": {"name": "Nosirov Samandar",           "password": "20635", "group": "nF-2941"},
    "1424113": {"name": "Qasimov Shohruh",            "password": "87543", "group": "nF-2941"},
    "1421419": {"name": "Sharipov Sunatilla",         "password": "98617", "group": "nF-2941"},
    "1424847": {"name": "Sultonov Ahmadjon",          "password": "09563", "group": "nF-2941"},
    "1423534": {"name": "Yuldoshev Diyorbek",         "password": "25684", "group": "nF-2941"},
    "1421052": {"name": "Zoyirov Shaxobiddin",        "password": "19257", "group": "nF-2941"},
    "1386137": {"name": "Rahimjonova Mushtariybonu",  "password": "83015", "group": "nF-2941"},
    "1400696": {"name": "Toraboyev Abdumo'min",       "password": "39814", "group": "nF-2941"},
    "1253049": {"name": "Alisherov Mahmudjon",        "password": "28159", "group": "nF-2941"},
    "1371168": {"name": "Turobov Islom",              "password": "96137", "group": "nF-2941"},
    # ── nF-2957 ──────────────────────────────────────────────────────────────
    "1409975": {"name": "Abdullayev Zafarbek",        "password": "39745", "group": "nF-2957"},
    "1403279": {"name": "Komilov Yusufjon",           "password": "56239", "group": "nF-2957"},
    "1407161": {"name": "Raximov Mirzohid",           "password": "95407", "group": "nF-2957"},
    "1406815": {"name": "Ravshanbekov Uchqunbek",     "password": "96073", "group": "nF-2957"},
    "1373702": {"name": "Ziyatov Shaxriyor",          "password": "05419", "group": "nF-2957"},
    "1094377": {"name": "Rixsiyev Ashraf",            "password": "18430", "group": "nF-2957"},
    "1414083": {"name": "Muhammadjonov Akbarjon",     "password": "41863", "group": "nF-2957"},
    "1413565": {"name": "Saidullohojayev Saidazim",   "password": "78124", "group": "nF-2957"},
    "1306449": {"name": "Arzuddinov Bunyod",          "password": "74896", "group": "nF-2957"},
    "1306455": {"name": "Arzuddinov Farrux",          "password": "76095", "group": "nF-2957"},
    "1298402": {"name": "Azimov Abduqodir",           "password": "63091", "group": "nF-2957"},

    # ── 2996-Pro ─────────────────────────────────────────────────────────────
    "1053838": {"name": "Sunnatxo'jayev Boisxon",     "password": "94703", "group": "2996-Pro"},
    "1143086": {"name": "Baxtiyorov Suhrobek",        "password": "60479", "group": "2996-Pro"},
    "935267":  {"name": "Xoliboyev Doniyor",          "password": "47612", "group": "2996-Pro"},
    "1027372": {"name": "Qudratov Qudratjon",         "password": "54092", "group": "2996-Pro"},
    "1156370": {"name": "Sobirov Aziz",         "password": "47532", "group": "2996-Pro"},

    # ── 2997-Pro ─────────────────────────────────────────────────────────────
    "1146165": {"name": "Mominjonov Akbar",           "password": "03547", "group": "2997-Pro"},
    "1115299": {"name": "Abdulazizov Jahongir",       "password": "61207", "group": "2997-Pro"},
    "1116290": {"name": "A'loyev Sardorxo'ja",        "password": "20314", "group": "2997-Pro"},
    "1118584": {"name": "Yalgasheva Sitora",          "password": "70139", "group": "2997-Pro"},
    "1031560": {"name": "Baxtiyorov Hayotbek",        "password": "89543", "group": "2997-Pro"},
    "1165391": {"name": "Nosiraliyev Muhammadyahyo",  "password": "42015", "group": "2997-Pro"},
    "1228619": {"name": "Hudoyberdiyev Azizbek",      "password": "6437892", "group": "2997-Pro"},

    # ── nFPro-120 ─────────────────────────────────────────────────────────────
    "842138":  {"name": "Aliyev Azizbek",             "password": "83145", "group": "nFPro-120"},
    "1229261": {"name": "Fazilov Kamron",             "password": "21759", "group": "nFPro-120"},
    "1064165": {"name": "Abdullayev Bobur",           "password": "46817", "group": "nFPro-120"},
}

MARS_GROUPS: list[str] = [
    "nF-2506", "nF-2694", "nF-2749", "nF-2803", "nF-2941", "nF-2957",
    "2996-Pro", "2997-Pro", "nFPro-120",
]

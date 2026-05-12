

def shifr(password: str):
    seq_password = list(password.lower())
    ans_eng = {
        'a': 1, 'b': 2, 'c': 3, 'd': 4, 'e': 5,
        'f': 6, 'g': 7, 'h': 8, 'i': 9, 'j': 10,
        'k': 11, 'l': 12, 'm': 13, 'n': 14, 'o': 15,
        'p': 16, 'q': 17, 'r': 18, 's': 19, 't': 20,
        'u': 21, 'v': 22, 'w': 23, 'x': 24, 'y': 25, 'z': 26
    }
    
    ans_ru = {
        'а': 27, 'б': 28, 'в': 29, 'г': 30, 'д': 31, 'е': 32, 'ё': 33,
        'ж': 34, 'з': 35, 'и': 36, 'й': 37, 'к': 38, 'л': 39, 'м': 40,
        'н': 41, 'о': 42, 'п': 43, 'р': 44, 'с': 45, 'т': 46, 'у': 47,
        'ф': 48, 'х': 49, 'ц': 50, 'ч': 51, 'ш': 52, 'щ': 53, 'ъ': 54,
        'ы': 55, 'ь': 56, 'э': 57, 'ю': 58, 'я': 59
    }
    for i in range(len(seq_password)):
        if seq_password[i] in ans_eng:
            seq_password[i] = str(ans_eng[seq_password[i]]+5)
        if seq_password[i] in ans_ru:
            seq_password[i] = str(ans_ru[seq_password[i]]+5)
    return(''.join(seq_password))


# translator.py - Language translation service
import requests

class Translator:
    def __init__(self):
        pass
    
    def translate_text(self, text, target_language):
        """Translate text to target language (English or Kiswahili)"""
        if not text or text.strip() == "":
            return text
        
        if target_language == "English":
            return text
        
        # Manual translations for common dashboard terms
        translations = {
            'PATIENT DASHBOARD': 'DASHIBODI YA MGONJWA',
            'DOCTOR DASHBOARD': 'DASHIBODI YA DOKTA',
            'DASHBOARD': 'DASHIBODI',
            'MESSAGES': 'UJUMBE',
            'MEDICATION LOG': 'REKODI YA DAWA',
            'VOICE REPORTS': 'RIPOTI ZA SAUTI',
            'FIND HOSPITAL': 'TAFUTA HOSPITALI',
            'SETTINGS': 'MIPANGILIO',
            'REFRESH': 'ONYESHA UPYA',
            'LOGOUT': 'TOKA',
            'ADHERENCE RATE': 'KIWANGO CHA UZINGATIAJI',
            'TOTAL MESSAGES': 'JUMLA YA UJUMBE',
            'CURRENT STREAK': 'MSURURU WA SASA',
            'NEXT APPOINTMENT': 'UTEuzi UJAO',
            'QUICK HEALTH REPORT': 'RIPOTI YA AFYA YA HARAKA',
            'SMS REPORT': 'RIPOTI KWA SMS',
            'VOICE REPORT': 'RIPOTI KWA SAUTI',
            'SEND REPORT': 'TUMA RIPOTI',
            'MESSAGE HISTORY': 'HISTORIA YA UJUMBE',
            'From: Doctor': 'Kutoka: Daktari',
            'To: Doctor': 'Kwa: Daktari',
            'ACCOUNT SETTINGS': 'MIPANGILIO YA AKAUNTI',
            'PERSONAL INFORMATION': 'TAARIFA ZA BINAFSI',
            'Patient ID': 'Kitambulisho cha Mgonjwa',
            'Location': 'Eneo',
            'MEDICATION SETTINGS': 'MIPANGILIO YA DAWA',
            'ARV Regimen': 'Mpango wa ARV',
            'Medication Time': 'Saa ya Dawa',
            'Reminder': 'Kumbusho',
            'Daily SMS reminder enabled': 'Kumbusho la SMS la kila siku limewashwa',
            'LANGUAGE PREFERENCE': 'UPENDELEO WA LUGHA',
            'Current Language': 'Lugha ya Sasa',
            'UPDATE LOCATION': 'SASISHA ENEO',
            'SAVE LANGUAGE': 'HIFADHI LUGHA',
            'English': 'Kiingereza',
            'Kiswahili': 'Kiswahili',
            'Voice Call Reporting': 'Kuripoti kwa Simu ya Sauti',
            'START VOICE CALL': 'ANZA SIMU',
            'FIND NEAREST HOSPITAL': 'TAFUTA HOSPITALI ILIYO KARIBU',
            'SELECT YOUR LOCATION / VILLAGE': 'CHAGUA ENEO/KIJIJI CHAKO',
            'NEAREST HOSPITAL': 'HOSPITALI ILIYO KARIBU',
            'Name': 'Jina',
            'Distance': 'Umbali',
            'Travel Time': 'Muda wa Kusafiri',
            'Phone': 'Simu',
            'Address': 'Anwani',
            'Hours': 'Saa',
            'Directions': 'Maelekezo',
            'REGISTER PATIENT': 'SAJILI MGONJWA',
            'ALL REGISTERED PATIENTS': 'WAGONJWA WOTE WALIOSAJILIWA',
            'RECENT PATIENTS': 'WAGONJWA WA HIVI KARIBUNI',
            'PROVIDER PORTAL': 'LANGA LA MTOA HUDUMA',
            'CONFIDENTIAL - Patient Identity Protected': 'SIRI - Utambulisho wa Mgonjwa Umelindwa'
        }
        
        # Check for exact match
        text_upper = text.upper().strip()
        if text_upper in translations:
            return translations[text_upper]
        
        # Check for partial match in button texts
        for eng, swa in translations.items():
            if eng in text_upper or eng in text:
                return text.replace(eng, swa)
        
        return text

translator = Translator()
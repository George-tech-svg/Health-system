# ai_engine.py - AI-powered text analysis for English and Kiswahili
import re

class AIEngine:
    def __init__(self):
        self.emergency_keywords = {
            'bleeding': ['bleeding', 'blood', 'haemorrhage', 'hemorrhage', 'damu'],
            'severe_pain': ['severe pain', 'excruciating', 'unbearable', 'maumivu makali', 'uma sana', 'painful'],
            'breathing': ['difficulty breathing', 'shortness of breath', 'can\'t breathe', 'kupumua', 'shida kupumua'],
            'fainting': ['fainted', 'passed out', 'unconscious', 'syncope', 'kuzirai', 'poteza fahamu'],
            'allergic': ['allergic reaction', 'swelling', 'rash all over', 'mzio', 'uvimbe']
        }
        
        self.moderate_keywords = {
            'fever': ['fever', 'high temperature', 'homa', 'joto kali', 'cold', 'baridi'],
            'vomiting': ['vomiting', 'throwing up', 'nausea', 'tapika', 'kichefuchefu', 'sickness'],
            'headache': ['headache', 'head pain', 'kichwa', 'umivu wa kichwa', 'migraine'],
            'diarrhea': ['diarrhea', 'loose stool', 'kuhara', 'endesha', 'stomach issues'],
            'fatigue': ['tired', 'fatigue', 'weak', 'exhausted', 'choka', 'uchovu', 'lethargy']
        }
        
        self.positive_keywords = ['better', 'good', 'fine', 'well', 'feeling good', 'nzuri', 'sawa', 'poa', 'great', 'excellent']
        self.refill_keywords = ['refill', 'dawa imekwisha', 'medication finished', 'no pills', 'imeisha', 'out of medication']
    
    def analyze_text(self, text, language='auto'):
        text_lower = text.lower()
        detected_lang = self._detect_language(text_lower)
        
        for severity, keywords in self.emergency_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return {
                        'risk_level': 'high',
                        'symptoms': [severity],
                        'response': self._get_emergency_response(detected_lang),
                        'requires_hospital': True
                    }
        
        detected_symptoms = []
        for symptom, keywords in self.moderate_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    detected_symptoms.append(symptom)
        
        for keyword in self.refill_keywords:
            if keyword in text_lower:
                return {
                    'risk_level': 'medium',
                    'symptoms': detected_symptoms + ['refill_needed'],
                    'response': self._get_refill_response(detected_lang),
                    'requires_hospital': False
                }
        
        for keyword in self.positive_keywords:
            if keyword in text_lower:
                return {
                    'risk_level': 'low',
                    'symptoms': detected_symptoms,
                    'response': self._get_positive_response(detected_lang),
                    'requires_hospital': False
                }
        
        if detected_symptoms:
            return {
                'risk_level': 'medium',
                'symptoms': detected_symptoms,
                'response': self._get_monitoring_response(detected_lang, detected_symptoms),
                'requires_hospital': False
            }
        
        return {
            'risk_level': 'low',
            'symptoms': [],
            'response': self._get_routine_response(detected_lang),
            'requires_hospital': False
        }
    
    def _detect_language(self, text):
        kiswahili_patterns = ['nina', 'una', 'ana', 'tuna', 'wana', 'kwa', 'kwenye', 'saa', 'asante', 'karibu', 'tafadhali', 'nime']
        for pattern in kiswahili_patterns:
            if pattern in text:
                return 'Kiswahili'
        return 'English'
    
    def _get_emergency_response(self, language):
        if language == 'Kiswahili':
            return "HATARI! Nenda hospitali ya karibu MARA MOJA. Daktari amepewa taarifa."
        else:
            return "EMERGENCY! Go to the nearest hospital IMMEDIATELY. Doctor has been notified."
    
    def _get_refill_response(self, language):
        if language == 'Kiswahili':
            return "Dawa zako zitakuwa tayari kwenye pharmacy kesho. Tembelea pharmacy yako."
        else:
            return "Your medication will be ready at the pharmacy tomorrow. Please visit your pharmacy."
    
    def _get_positive_response(self, language):
        if language == 'Kiswahili':
            return "Habari njema! Endelea na dawa zako. Tuko nawe."
        else:
            return "Great news! Keep up the good work with your medication."
    
    def _get_monitoring_response(self, language, symptoms):
        if language == 'Kiswahili':
            return f"Tumepokea taarifa yako. Pumzika. Kama hali inazidi kuwa mbaya, tembelea kliniki yako."
        else:
            return f"We've received your report. Rest. If symptoms worsen, please visit your clinic."
    
    def _get_routine_response(self, language):
        if language == 'Kiswahili':
            return "Asante kwa taarifa yako. Endelea na dawa kama ilivyoagizwa."
        else:
            return "Thank you for your report. Continue taking your medication as prescribed."
    
    def find_nearest_hospital(self, patient_location):
        hospitals = {
            "Siaya Town": "Siaya County Referral Hospital - 2km away. Call 057-123456",
            "Bondo": "Bondo Sub-County Hospital - 1.5km away. Call 057-345678",
            "Kisumu": "Jaramogi Oginga Odinga Hospital - 3km away. Call 057-456789",
            "Rangala": "Rangala Health Centre - 1km away. Call 057-567890",
            "Ugunja": "Ugunja Sub-County Hospital - 2.5km away. Call 057-678901"
        }
        return hospitals.get(patient_location, "Your nearest health facility.")
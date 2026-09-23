# voice_simulator.py - Voice call reporting simulation (No external dependencies)
class VoiceSimulator:
    def __init__(self, ai_engine, sms_handler, database):
        self.ai_engine = ai_engine
        self.sms_handler = sms_handler
        self.db = database
    
    def simulate_voice_call(self, patient_phone=None, pre_recorded_message=None):
        """Simulate a voice call interaction - works without speechrecognition"""
        print("\n" + "="*50)
        print("VOICE CALL SYSTEM (SIMULATED)")
        print("="*50)
        
        if pre_recorded_message:
            transcribed_text = pre_recorded_message
            print(f"Message: {transcribed_text}")
        else:
            # For simulation, use text input instead of real voice
            transcribed_text = input("Type your message (simulated voice): ")
        
        patients = self.db.get_all_patients()
        patient = None
        for p in patients:
            if patient_phone and p[3] == patient_phone:
                patient = p
                break
        
        if not patient and patients:
            patient = patients[0]
        
        if patient:
            analysis = self.ai_engine.analyze_text(transcribed_text, patient[4])
            
            self.db.save_message(
                patient[1], 'incoming', 'voice', transcribed_text, patient[4],
                analysis['risk_level'], ','.join(analysis['symptoms']), analysis['response']
            )
            
            self.sms_handler.send_sms(patient[3], analysis['response'], patient[4])
            
            if analysis['risk_level'] == 'high':
                hospital = self.ai_engine.find_nearest_hospital(patient[5])
                self.sms_handler.send_sms(patient[3], f"HOSPITAL REFERRAL: {hospital}", patient[4])
            
            return analysis
        
        return {'response': 'Patient not found'}

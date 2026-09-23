# sms_handler.py - SMS handling for FastAfya (No chat saving)
class SMSHandler:
    def __init__(self, ai_engine, database):
        self.ai_engine = ai_engine
        self.db = database
    
    def send_sms(self, phone_number, message, language='English'):
        # This is for medication reminders and alerts - NOT chat messages
        print(f"\n📱 SMS SENT to {phone_number}: {message}\n")
        # Do NOT save to messages table (these are notifications, not chat)
        return {"status": "success"}
    
    def receive_sms(self, phone_number, message_text):
        # For patient reports via SMS
        print(f"\n📱 SMS RECEIVED from {phone_number}: {message_text}\n")
        return {"status": "received"}
    
    def _trigger_emergency(self, patient, original_message, analysis):
        print(f"\n🚨 EMERGENCY ALERT! Patient: {patient[2]} ({patient[1]})")
        hospital_info = self.ai_engine.find_nearest_hospital(patient[5])
        self.send_sms(patient[3], f"HOSPITAL REFERRAL: {hospital_info}", patient[4])

class AfricaTalkingSandbox:
    @staticmethod
    def simulate_sms_flow():
        print("\nAfrica's Talking SMS Simulation")
    
    @staticmethod
    def simulate_voice_flow():
        print("\nAfrica's Talking Voice Simulation")
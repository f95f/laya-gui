from laya import Router

router = Router()

state = {
    "message": "this message contain abuse"
}

questions = {
    "spam": {
        "type": "choice",
        "instructions": "Is this message spam?",
        "criteria": {
            "clean": "normal user message",
            "promo": "unsolicited promotion or repeated marketing",
            "scam": "fraud, phishing, fake offer, credential theft",
            "bot": "automated or repetitive low-value message"
        }
    },
    "abuse": {
        "type": "choice",
        "instructions": "Does this message contain abuse?",
        "criteria": {
            "none": "no abuse",
            "insult": "personal attack or harassment",
            "hate": "protected-class hate or dehumanization",
            "threat": "violent threat or intimidation",
            "sexual": "sexual harassment or explicit unwanted content"
        }
    }
}

result = router.predict(state, questions)
print(result)
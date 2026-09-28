import gradio as gr
from laya import Router

router = Router()

questions = {
    "spam": {
        "type": "choice",
        "instructions": "Is this message spam?",
	"criteria": {
 	   "A": "normal user message",
 	   "B": "unsolicited promotion, repeated marketing, or link farming",
 	   "C": "fraud, phishing, fake offer, credential theft",
  	  "D": "automated or repetitive low-value message"
	}
    },
    "abuse": {
        "type": "choice",
        "instructions": "Does this message contain abuse?",
	"criteria": {
	    "A": "no abuse",
 	   "B": "personal attack or harassment",
 	   "C": "protected-class hate or dehumanization",
	    "D": "violent threat or intimidation",
 	   "E": "sexual harassment or explicit unwanted content"
	}
    }
}

def classify(message):
    result = router.predict({"message": message}, questions)
    return result

demo = gr.Interface(
    fn=classify,
    inputs=gr.Textbox(lines=5, label="Message"),
    outputs=gr.JSON(label="Laya result"),
    title="Laya Spam / Abuse Checker"
)

demo.launch()
"""Generátor JSON testů pro přijímačky.

Použití (volitelné):
- spustit lokálně a přepsat a2_test.json / b1_b2_test.json / c1_c2_test.json

Cíl: mít kolem 30 bodovaných otázek na každou úroveň.

Pozn.: Nechceme externí API ani frameworky. Otázky jsou "hand-made" šablonovitě, ale validní a konzistentní.
"""

from __future__ import annotations

import json
import pathlib

BASE_DIR = pathlib.Path(__file__).resolve().parent


def _write(name: str, data: dict) -> None:
    (BASE_DIR / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def a2() -> dict:
    # 30 bodovaných: grammar 10 + vocab 10 + reading 4 + transform 3 + listening 2 + writing(mcq) 1 = 30
    grammar = []
    for i, (p, opts, corr, expl) in enumerate(
            [
                ("I ___ to school every day.", ["go", "goes", "going", "gone"], "go", "Present simple: I go."),
                ("She ___ in Brno.", ["live", "lives", "living", "lived"], "lives", "3rd person singular: lives."),
                ("They ___ TV now.", ["watch", "watches", "are watching", "watched"], "are watching",
                 "Present continuous: are watching."),
                ("We ___ a dog.", ["has", "have", "having", "had"], "have", "I/you/we/they: have."),
                ("He ___ like coffee.", ["don't", "doesn't", "isn't", "can't"], "doesn't", "He/She/It: doesn't."),
                ("___ you play tennis?", ["Do", "Does", "Did", "Are"], "Do", "Questions with do for you/we/they."),
                ("I was born ___ 2008.", ["in", "on", "at", "for"], "in", "Years: in 2008."),
                ("There ___ some milk in the fridge.", ["is", "are", "be", "were"], "is", "Uncountable: is."),
                (
                "We ___ to the cinema yesterday.", ["go", "went", "gone", "going"], "went", "Past simple of go: went."),
                ("Can you ___ me?", ["help", "helps", "helping", "helped"], "help", "Modal verb + base form."),
            ],
            start=1,
    ):
        grammar.append(
            {
                "id": f"a2-g-{i}",
                "format": "mcq",
                "prompt": p,
                "options": opts,
                "correct": [corr],
                "explanation": expl,
            }
        )

    vocab = []
    vocab_items = [
        ("I'm ___ because I worked all day.", ["tired", "hungry", "angry", "cold"], "tired", "Tired = unavený."),
        ("Can I have a glass of ___, please?", ["water", "rice", "bread", "tea"], "water", "A glass of water."),
        ("My uncle is a ___. He works in a hospital.", ["teacher", "doctor", "driver", "singer"], "doctor",
         "Hospital → doctor."),
        ("I usually ___ a shower in the morning.", ["do", "make", "take", "have"], "have",
         "Collocation: have a shower."),
        ("Opposite of 'cheap' is ___.", ["expensive", "small", "late", "old"], "expensive", "cheap ↔ expensive."),
        ("I need to buy some ___.", ["food", "chairs", "cars", "keys"], "food", "General word: food."),
        ("False friend: 'actual' means:", ["skutečný", "aktuální", "herec", "aktivní"], "skutečný", "Actual = real."),
        ("We ___ a bus at the bus stop.", ["wait", "wait for", "waits", "waiting"], "wait for", "wait for something."),
        ("It's ___ today. Let's wear a jacket.", ["sunny", "warm", "cold", "easy"], "cold", "Cold → jacket."),
        ("Choose: I ___ my homework every day.", ["do", "make", "take", "get"], "do", "do homework."),
    ]
    for i, (p, opts, corr, expl) in enumerate(vocab_items, start=1):
        vocab.append(
            {
                "id": f"a2-v-{i}",
                "format": "mcq",
                "prompt": p,
                "options": opts,
                "correct": [corr],
                "explanation": expl,
            }
        )

    reading_passage = (
        "Hi! My name is Tom. I'm 16 years old and I live in a small town. On weekdays, I get up at 6:30, have breakfast, "
        "and go to school by bus. After school, I usually do my homework and then I play football with my friends. "
        "At the weekend, I like watching movies and visiting my grandparents."
    )
    reading = [
        {
            "id": "a2-r-1",
            "format": "mcq",
            "prompt": "How does Tom go to school?",
            "options": ["By bus", "By car", "On foot", "By train"],
            "correct": ["By bus"],
            "explanation": "In the text: 'go to school by bus'.",
        },
        {
            "id": "a2-r-2",
            "format": "true_false",
            "prompt": "Tom plays football after school.",
            "options": ["True", "False"],
            "correct": ["True"],
            "explanation": "In the text: 'I play football with my friends'.",
        },
        {
            "id": "a2-r-3",
            "format": "mcq",
            "prompt": "What does Tom do at the weekend?",
            "options": ["He visits grandparents", "He works", "He goes to school", "He sleeps all day"],
            "correct": ["He visits grandparents"],
            "explanation": "Weekend: visiting grandparents.",
        },
        {
            "id": "a2-r-4",
            "format": "mcq",
            "prompt": "How old is Tom?",
            "options": ["15", "16", "17", "18"],
            "correct": ["16"],
            "explanation": "He says: I'm 16 years old.",
        },
    ]

    transform = [
        {
            "id": "a2-t-1",
            "format": "transform",
            "prompt": "Rewrite using 'because': I stayed at home. I was sick.",
            "correct": ["I stayed at home because I was sick."],
            "alternatives": ["Because I was sick, I stayed at home."],
            "explanation": "because spojuje věty.",
        },
        {
            "id": "a2-t-2",
            "format": "transform",
            "prompt": "Rewrite using 'and': I like tea. I like coffee.",
            "correct": ["I like tea and coffee."],
            "alternatives": ["I like tea and I like coffee."],
            "explanation": "Spojíme pomocí and.",
        },
        {
            "id": "a2-t-3",
            "format": "transform",
            "prompt": "Rewrite using 'can': It is possible for me to swim.",
            "correct": ["I can swim."],
            "alternatives": ["I can swim"],
            "explanation": "Can vyjadřuje schopnost.",
        },
    ]

    listening_passage = "(Listening text) The train to Prague will leave from platform 3 at 10:15."
    listening = [
        {
            "id": "a2-l-1",
            "format": "mcq",
            "prompt": "What platform will the train leave from?",
            "options": ["1", "2", "3", "4"],
            "correct": ["3"],
            "explanation": "It says platform 3.",
        },
        {
            "id": "a2-l-2",
            "format": "mcq",
            "prompt": "What time will it leave?",
            "options": ["9:15", "10:15", "11:15", "12:15"],
            "correct": ["10:15"],
            "explanation": "It says 10:15.",
        },
    ]

    writing = [
        {
            "id": "a2-w-1",
            "format": "short_answer",
            "prompt": "Write 1–2 sentences: Describe your favourite hobby.",
            "correct": [],
            "alternatives": [],
            "explanation": "Otevřená odpověď (nepočítá se do skóre).",
        },
        {
            "id": "a2-w-2",
            "format": "mcq",
            "prompt": "Choose the best closing for an email to a friend:",
            "options": ["Yours faithfully,", "Best wishes,", "Dear Sir or Madam,", "To whom it may concern,"],
            "correct": ["Best wishes,"],
            "explanation": "Neformální email.",
        },
    ]

    return {
        "id": "prijmacky-a2-001",
        "level": "A2",
        "time_limit": 35,
        "sections": [
            {"type": "grammar", "title": "Grammar & Use of English", "questions": grammar},
            {"type": "vocabulary", "title": "Vocabulary", "questions": vocab},
            {"type": "reading", "title": "Reading comprehension", "passage": reading_passage, "questions": reading},
            {"type": "transformation", "title": "Sentence transformation", "questions": transform},
            {"type": "listening", "title": "Listening (placeholder)", "audio": None, "passage": listening_passage,
             "questions": listening},
            {"type": "writing", "title": "Writing (short)", "questions": writing},
        ],
    }


def b1b2() -> dict:
    # 30 bodovaných: grammar 10 + vocab 10 + reading 4 + transform 3 + listening 2 + writing(mcq) 1 = 30
    grammar_items = [
        ("I ___ never been to London.", ["have", "has", "had", "having"], "have", "Present perfect."),
        ("If I ___ more time, I would travel more.", ["have", "had", "has", "having"], "had", "Second conditional."),
        ("She suggested ___ by train.", ["go", "going", "to go", "gone"], "going", "Suggest + -ing."),
        ("By the time we arrived, the film ___.", ["started", "had started", "starts", "has started"], "had started",
         "Past perfect."),
        ("You ___ smoke here. It's forbidden.", ["must", "mustn't", "don't have to", "should"], "mustn't",
         "Prohibition."),
        ("I wish I ___ taller.", ["am", "was", "were", "will be"], "were", "Wish + past (were)."),
        ("He said he ___ help me later.", ["will", "would", "can", "must"], "would", "Reported speech: will→would."),
        ("Neither Tom nor Jane ___ coming.", ["is", "are", "were", "be"], "is", "Neither...nor: agreement."),
        ("I look forward to ___ from you.", ["hear", "hearing", "to hear", "heard"], "hearing",
         "look forward to + -ing."),
        ("This is the person ___ car was stolen.", ["who", "which", "whose", "whom"], "whose", "Possessive relative."),
    ]
    grammar = [
        {"id": f"b1-g-{i}", "format": "mcq", "prompt": p, "options": o, "correct": [c], "explanation": e}
        for i, (p, o, c, e) in enumerate(grammar_items, start=1)
    ]

    vocab_items = [
        ("He finally ___ a decision.", ["did", "made", "took", "put"], "made", "make a decision."),
        ("This film is really ___.", ["excite", "exciting", "excited", "excitement"], "exciting",
         "-ing describes the thing."),
        ("False friend: 'eventually' means:", ["nakonec", "eventuálně", "případně", "okamžitě"], "nakonec",
         "Eventually = in the end."),
        ("She applied ___ the job.", ["for", "to", "at", "in"], "for", "apply for a job."),
        ("I can't ___ to buy it.", ["affect", "afford", "effort", "avoid"], "afford", "afford = mít dost peněz."),
        ("The lecture was so ___ that I nearly fell asleep.", ["boring", "bored", "interest", "interested"], "boring",
         "-ing describes the lecture."),
        ("He is responsible ___ the project.", ["of", "for", "to", "with"], "for", "responsible for."),
        ("Let's ___ up this issue tomorrow.", ["bring", "take", "make", "do"], "bring", "bring up = otevřít téma."),
        ("We ran ___ sugar, so I went to the shop.", ["out of", "into", "over", "up"], "out of", "run out of."),
        ("I prefer tea ___ coffee.", ["than", "to", "from", "with"], "to", "prefer X to Y."),
    ]
    vocab = [
        {"id": f"b1-v-{i}", "format": "mcq", "prompt": p, "options": o, "correct": [c], "explanation": e}
        for i, (p, o, c, e) in enumerate(vocab_items, start=1)
    ]

    passage = (
        "When I started university, I expected to have lots of free time. However, I quickly realised that studying required "
        "much more organisation than I had imagined. Between lectures, part-time work, and preparing for exams, my days became "
        "surprisingly busy. The biggest change was learning how to plan ahead: I now write weekly to-do lists and set realistic goals. "
        "Although it can be stressful, I feel more independent and confident than before."
    )
    reading = [
        {
            "id": "b1-r-1",
            "format": "mcq",
            "prompt": "What did the writer NOT expect about university?",
            "options": ["Having lots of free time", "Needing organisation", "Being busy", "Planning ahead"],
            "correct": ["Needing organisation"],
            "explanation": "They expected free time, not organisation.",
        },
        {
            "id": "b1-r-2",
            "format": "true_false",
            "prompt": "The writer feels less confident now.",
            "options": ["True", "False"],
            "correct": ["False"],
            "explanation": "They feel more confident.",
        },
        {
            "id": "b1-r-3",
            "format": "mcq",
            "prompt": "What helps the writer plan better?",
            "options": ["Weekly to-do lists", "More lectures", "Less work", "No exams"],
            "correct": ["Weekly to-do lists"],
            "explanation": "They write weekly to-do lists.",
        },
        {
            "id": "b1-r-4",
            "format": "mcq",
            "prompt": "Which statement is true?",
            "options": ["University was easier than expected", "Days became busy", "They stopped working",
                        "They hate planning"],
            "correct": ["Days became busy"],
            "explanation": "It became surprisingly busy.",
        },
    ]

    transform = [
        {
            "id": "b1-t-1",
            "format": "transform",
            "prompt": "Rewrite using the word 'used' (do not change it): I often went swimming when I was a child.",
            "correct": ["I used to go swimming when I was a child."],
            "alternatives": ["When I was a child, I used to go swimming."],
            "explanation": "used to = zvyky v minulosti.",
        },
        {
            "id": "b1-t-2",
            "format": "transform",
            "prompt": "Finish the sentence so it means the same: It's the first time I've tried sushi. I have never ___ before.",
            "correct": ["tried sushi"],
            "alternatives": ["tried sushi before"],
            "explanation": "never tried sushi (before).",
        },
        {
            "id": "b1-t-3",
            "format": "transform",
            "prompt": "Rewrite: I'm too tired to study. (use 'so')",
            "correct": ["I am so tired that I can't study."],
            "alternatives": ["I'm so tired that I cannot study."],
            "explanation": "so...that.",
        },
    ]

    listening_passage = (
        "(Listening text) The teacher says the lesson is cancelled today because she is ill, and it will take place next Monday at the usual time."
    )
    listening = [
        {
            "id": "b1-l-1",
            "format": "mcq",
            "prompt": "Why is the lesson cancelled?",
            "options": ["The teacher is ill", "The classroom is closed", "There is an exam", "The teacher is late"],
            "correct": ["The teacher is ill"],
            "explanation": "Because she is ill.",
        },
        {
            "id": "b1-l-2",
            "format": "mcq",
            "prompt": "When will the lesson take place instead?",
            "options": ["Tomorrow", "Next Monday", "Next Friday", "In two weeks"],
            "correct": ["Next Monday"],
            "explanation": "Next Monday.",
        },
    ]

    writing = [
        {
            "id": "b1-w-1",
            "format": "mcq",
            "prompt": "Choose the best sentence for the start of a semi-formal email:",
            "options": ["Yo! What's up?", "I am writing to ask for information about your course.", "Gimme details.",
                        "Hey teacher!"],
            "correct": ["I am writing to ask for information about your course."],
            "explanation": "Semi-formální styl.",
        },
        {
            "id": "b1-w-2",
            "format": "short_answer",
            "prompt": "Write 1–2 sentences: Reply to a friend who invited you to a party. Accept or refuse and give a reason.",
            "correct": [],
            "alternatives": [],
            "explanation": "Otevřená odpověď (nepočítá se do skóre).",
        },
    ]

    return {
        "id": "prijmacky-b1b2-001",
        "level": "B1-B2",
        "time_limit": 45,
        "sections": [
            {"type": "grammar", "title": "Grammar & Use of English", "questions": grammar},
            {"type": "vocabulary", "title": "Vocabulary", "questions": vocab},
            {"type": "reading", "title": "Reading comprehension", "passage": passage, "questions": reading},
            {"type": "transformation", "title": "Sentence transformation", "questions": transform},
            {"type": "listening", "title": "Listening (placeholder)", "audio": None, "passage": listening_passage,
             "questions": listening},
            {"type": "writing", "title": "Writing (short)", "questions": writing},
        ],
    }


def c1c2() -> dict:
    # 30 bodovaných: grammar 10 + vocab 10 + reading 4 + transform 3 + listening 2 + writing(mcq) 1 = 30
    grammar_items = [
        (
            "Hardly ___ the meeting started when the fire alarm went off.",
            ["had", "has", "did", "was"],
            "had",
            "Hardly + past perfect ... when + past simple.",
        ),
        (
            "No sooner ___ than she started complaining.",
            ["had she arrived", "she had arrived", "did she arrive", "has she arrived"],
            "had she arrived",
            "No sooner + inversion (past perfect).",
        ),
        (
            "Despite ___ the rain, the match continued.",
            ["of", "-", "on", "to"],
            "-",
            "Despite (bez of).",
        ),
        (
            "If he ___ earlier, he wouldn't have missed the train.",
            ["left", "had left", "would leave", "has left"],
            "had left",
            "Third conditional: If + past perfect.",
        ),
        (
            "Not only ___ he apologise, but he also denied everything.",
            ["did", "does", "has", "was"],
            "did",
            "Inversion after Not only.",
        ),
        (
            "It's about time you ___ to bed.",
            ["go", "went", "gone", "going"],
            "went",
            "It's about time + past simple.",
        ),
        (
            "She acts as if she ___ the boss.",
            ["is", "were", "has been", "will be"],
            "were",
            "As if + unreal past (were).",
        ),
        (
            "The report, ___ was published yesterday, caused a stir.",
            ["that", "which", "where", "who"],
            "which",
            "Non-defining relative clause.",
        ),
        (
            "Were I you, I ___ reconsider.",
            ["will", "would", "can", "must"],
            "would",
            "Inverted conditional: Were I you...",
        ),
        (
            "He demanded that she ___ immediately.",
            ["leaves", "leave", "left", "leaving"],
            "leave",
            "Subjunctive: demand that + base form.",
        ),
    ]
    grammar = [
        {"id": f"c1-g-{i}", "format": "mcq", "prompt": p, "options": o, "correct": [c], "explanation": e}
        for i, (p, o, c, e) in enumerate(grammar_items, start=1)
    ]

    vocab_items = [
        (
            "The CEO's speech was widely criticised for its ___ tone.",
            ["condescending", "condensing", "consecutive", "conclusive"],
            "condescending",
            "Condescending = povýšený.",
        ),
        (
            "The committee rejected the proposal, citing a lack of ___ evidence.",
            ["compelling", "random", "minor", "casual"],
            "compelling",
            "Compelling/convincing evidence.",
        ),
        (
            "False friend: 'sensible' means:",
            ["rozumný", "citlivý", "smyslový", "senzační"],
            "rozumný",
            "Sensible = rozumný.",
        ),
        (
            "The plan was abandoned due to ___ opposition.",
            ["fierce", "tiny", "fragile", "gentle"],
            "fierce",
            "Fierce opposition.",
        ),
        (
            "Her explanation was so ___ that nobody understood it.",
            ["convoluted", "convenient", "constant", "conclusive"],
            "convoluted",
            "Convoluted = zamotaný.",
        ),
        (
            "He gave a very ___ account of what happened.",
            ["candid", "candidate", "candle", "canal"],
            "candid",
            "Candid = upřímný.",
        ),
        (
            "The company is trying to ___ its image.",
            ["revamp", "revolt", "revise", "reveal"],
            "revamp",
            "Revamp = výrazně přepracovat.",
        ),
        (
            "The new policy will ___ small businesses.",
            ["adversely affect", "advantage", "address", "admire"],
            "adversely affect",
            "Adversely affect = negativně ovlivnit.",
        ),
        (
            "The results were ___ with earlier studies.",
            ["consistent", "confident", "convenient", "constant"],
            "consistent",
            "Consistent with.",
        ),
        (
            "He is known for his ___ sense of humour.",
            ["dry", "wet", "watery", "damp"],
            "dry",
            "Dry sense of humour.",
        ),
    ]
    vocab = [
        {"id": f"c1-v-{i}", "format": "mcq", "prompt": p, "options": o, "correct": [c], "explanation": e}
        for i, (p, o, c, e) in enumerate(vocab_items, start=1)
    ]

    passage = (
        "In an age of constant connectivity, the notion of 'digital minimalism' has gained traction among those who feel overwhelmed by endless notifications. "
        "Proponents argue that attention is a finite resource and that the default settings of many platforms are designed to maximise engagement rather than well-being. "
        "Yet critics contend that opting out can be a privilege: for some, social media is a vital tool for professional visibility, community building, or access to information that traditional institutions fail to provide. "
        "The debate, therefore, is less about technology itself than about agency—who controls it, who benefits from it, and how deliberately individuals choose to incorporate it into their lives."
    )
    reading = [
        {
            "id": "c1-r-1",
            "format": "mcq",
            "prompt": "What is the main point of the last sentence?",
            "options": [
                "Technology is always harmful",
                "The debate focuses on personal control and intentional use",
                "People should delete social media",
                "Notifications are the main problem",
            ],
            "correct": ["The debate focuses on personal control and intentional use"],
            "explanation": "It shifts focus to agency and intentional use.",
        },
        {
            "id": "c1-r-2",
            "format": "true_false",
            "prompt": "The text suggests that leaving social media is equally easy for everyone.",
            "options": ["True", "False"],
            "correct": ["False"],
            "explanation": "Opting out can be a privilege.",
        },
        {
            "id": "c1-r-3",
            "format": "mcq",
            "prompt": "What do critics argue?",
            "options": ["Minimalism is useless", "Opting out can be a privilege", "Notifications are fine",
                        "Agency doesn't matter"],
            "correct": ["Opting out can be a privilege"],
            "explanation": "Explicitly stated.",
        },
        {
            "id": "c1-r-4",
            "format": "mcq",
            "prompt": "What is the debate ultimately about?",
            "options": ["Phones", "Agency and control", "Advertising", "Wi‑Fi"],
            "correct": ["Agency and control"],
            "explanation": "Who controls it and benefits.",
        },
    ]

    transform = [
        {
            "id": "c1-t-1",
            "format": "transform",
            "prompt": "Rewrite using the word 'little' (do not change it): I didn't expect the discussion to become so heated.",
            "correct": ["Little did I expect the discussion to become so heated."],
            "alternatives": ["Little did I expect the debate to become so heated."],
            "explanation": "Inversion after Little.",
        },
        {
            "id": "c1-t-2",
            "format": "transform",
            "prompt": "Finish the sentence: It's possible that he misunderstood what you said. He may ___.",
            "correct": ["have misunderstood what you said"],
            "alternatives": ["have misunderstood"],
            "explanation": "may have + past participle.",
        },
        {
            "id": "c1-t-3",
            "format": "transform",
            "prompt": "Rewrite using 'not': It's unlikely that she will agree.",
            "correct": ["She is not likely to agree."],
            "alternatives": ["It is not likely that she will agree."],
            "explanation": "not likely.",
        },
    ]

    listening_passage = (
        "(Listening text) The speaker explains that short-term measures are popular, but long-term reforms require public support and clear communication about costs and benefits."
    )
    listening = [
        {
            "id": "c1-l-1",
            "format": "mcq",
            "prompt": "What do long-term reforms require?",
            "options": ["Less communication", "Public support and clear communication", "Only short-term measures",
                        "No costs"],
            "correct": ["Public support and clear communication"],
            "explanation": "Stated directly.",
        },
        {
            "id": "c1-l-2",
            "format": "mcq",
            "prompt": "What are short-term measures described as?",
            "options": ["Unpopular", "Popular", "Impossible", "Illegal"],
            "correct": ["Popular"],
            "explanation": "They are popular.",
        },
    ]

    writing = [
        {
            "id": "c1-w-1",
            "format": "mcq",
            "prompt": "Choose the most appropriate sentence for a formal email complaint:",
            "options": [
                "I'm really mad about this.",
                "I am writing to express my dissatisfaction with the service provided.",
                "This is a joke.",
                "Fix it ASAP.",
            ],
            "correct": ["I am writing to express my dissatisfaction with the service provided."],
            "explanation": "Formal register.",
        },
        {
            "id": "c1-w-2",
            "format": "short_answer",
            "prompt": "Write 1–2 sentences: Give an opinion on whether students should use AI to learn languages, and justify it.",
            "correct": [],
            "alternatives": [],
            "explanation": "Otevřená odpověď (nepočítá se do skóre).",
        },
    ]

    return {
        "id": "prijmacky-c1c2-001",
        "level": "C1-C2",
        "time_limit": 60,
        "sections": [
            {"type": "grammar", "title": "Grammar & Use of English", "questions": grammar},
            {"type": "vocabulary", "title": "Vocabulary", "questions": vocab},
            {"type": "reading", "title": "Reading comprehension", "passage": passage, "questions": reading},
            {"type": "transformation", "title": "Sentence transformation", "questions": transform},
            {"type": "listening", "title": "Listening (placeholder)", "audio": None, "passage": listening_passage,
             "questions": listening},
            {"type": "writing", "title": "Writing (short)", "questions": writing},
        ],
    }


def main() -> None:
    _write("a2_test.json", a2())
    _write("b1_b2_test.json", b1b2())
    _write("c1_c2_test.json", c1c2())
    print("OK: tests generated")


if __name__ == "__main__":
    main()

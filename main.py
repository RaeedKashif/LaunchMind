"""OutreachPilot — single entry point that runs the full multi-agent pipeline."""
from dotenv import load_dotenv
load_dotenv(override=True)

from message_bus import MessageBus
from agents.product_agent import ProductAgent
from agents.engineer_agent import EngineerAgent
from agents.marketing_agent import MarketingAgent
from agents.qa_agent import QAAgent
from agents.ceo_agent import CEOAgent


def main():
    print("=" * 60)
    print("  OutreachPilot — Multi-Agent System")
    print("  Starting autonomous agent pipeline...")
    print("=" * 60)

    bus = MessageBus()

    startup_idea = (
        "OutreachPilot — An AI-powered tool that helps Pakistan-based freelancers "
        "automate their US client outreach. Input your service focus and target audience, "
        "and the tool generates personalized LinkedIn connection messages, follow-up DMs, "
        "LinkedIn posts, cold outreach emails, and social media drafts — all tailored to "
        "the freelancer's specific service-audience combination."
    )
    service_focus = "AI Voice Call Agents"
    target_audience = (
        "Local US Business Owners — dental clinics, medical practices, gyms, salons, "
        "real estate agents, home service businesses (plumbers, HVAC, electricians). "
        "1-20 employees. Budget $200-$2,000 per project. They miss 30-40% of incoming "
        "calls and are losing customers to competitors who are available 24/7."
    )

    product = ProductAgent(bus)
    engineer = EngineerAgent(bus)
    marketing = MarketingAgent(bus)
    qa = QAAgent(bus)
    ceo = CEOAgent(bus, product, engineer, marketing, qa)

    ceo.run(startup_idea, service_focus, target_audience)

    bus.save_log("message_log.json")
    print("\n" + "=" * 60)
    print("  Pipeline complete. Message log saved to message_log.json")
    print("=" * 60)


if __name__ == "__main__":
    main()

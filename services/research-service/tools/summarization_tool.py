from typing import Any, Dict
from pydantic import BaseModel, Field
from packages.ai_core.tools.base_tool import BaseTool
from packages.ai_core.tools.context import ToolContext
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

class SummarizationInput(BaseModel):
    chunks: list[str] = Field(description="Extracted text chunks to synthesize.")
    focus_area: str = Field(default="general", description="Specific topic to focus the summary on.")

class SummarizationOutput(BaseModel):
    summary: str = Field(description="The synthesized summary.")
    key_findings: list[str] = Field(description="Bullet points of critical findings.")

class SummarizationTool(BaseTool):
    """
    Synthesizes and summarizes large amounts of retrieved RAG context.
    """
    name = "paper_summarization"
    description = "Synthesizes extracted text chunks into a coherent summary."
    tags = ["analysis", "research"]
    input_schema = SummarizationInput
    output_schema = SummarizationOutput

    def __init__(self, llm=None):
        # Use OpenRouter with Nemotron if not provided
        if llm is None:
            from packages.ai_core.models.config import config
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                openai_api_key=config.openrouter_api_key,
                openai_api_base="https://openrouter.ai/api/v1",
                model_name="nvidia/nemotron-3.5-lightning:free",
                temperature=0.2
            )
        self.llm = llm
        
        template = """
        You are an expert AI Research assistant. Summarize the following extracted text chunks, 
        focusing specifically on: {focus_area}.
        
        Extracted Text:
        {text}
        
        Provide the output strictly in the following format:
        SUMMARY:
        <Write a comprehensive summary>
        
        KEY FINDINGS:
        - <finding 1>
        - <finding 2>
        """
        self.prompt = PromptTemplate(template=template, input_variables=["focus_area", "text"])
        self.chain = self.prompt | self.llm

    async def execute(self, inputs: SummarizationInput, context: ToolContext) -> SummarizationOutput:
        text_to_summarize = "\\n\\n".join(inputs.chunks)
        
        response = await self.chain.ainvoke({
            "focus_area": inputs.focus_area,
            "text": text_to_summarize
        })
        
        content = response.content
        summary_part = ""
        findings_part = []
        
        if "KEY FINDINGS:" in content:
            parts = content.split("KEY FINDINGS:")
            summary_part = parts[0].replace("SUMMARY:", "").strip()
            findings_text = parts[1].strip()
            findings_part = [line.replace("-", "").strip() for line in findings_text.split("\\n") if line.strip().startswith("-")]
        else:
            summary_part = content
            
        return SummarizationOutput(
            summary=summary_part,
            key_findings=findings_part
        )

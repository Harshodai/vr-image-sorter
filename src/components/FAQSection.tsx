import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';

const faqs = [
  {
    question: 'What barcode formats are supported?',
    answer: 'The scanner supports standard 1D barcodes. It also uses OCR (Optical Character Recognition) as a fallback to read VR codes directly from images.',
  },
  {
    question: 'What image formats can I upload?',
    answer: 'We support JPG, JPEG, and PNG image formats. Make sure your images are clear and the barcode/VR code is visible.',
  },
  {
    question: 'How does the scanning process work?',
    answer: 'The system first attempts barcode scanning with various image preprocessing techniques. If no barcode is found, it falls back to OCR scanning to detect VR codes in the image.',
  },
  {
    question: 'Why do some images fail to process?',
    answer: 'Images may fail if the barcode is damaged, blurry, or not visible. Images without valid VR codes will also fail. Failed images are automatically retried once.',
  },
  {
    question: 'Is there a limit on how many images I can upload?',
    answer: 'For optimal performance, we recommend processing up to 100 images at a time. Larger batches may take longer to process.',
  },
  {
    question: 'How are the output files named?',
    answer: 'Successfully processed files are renamed to their VR code (e.g., VR89056.jpg). If duplicates exist, a number suffix is added (e.g., VR89056_1.jpg).',
  },
];

export function FAQSection() {
  return (
    <section className="py-12 border-t border-border mt-12">
      <h2 className="text-2xl font-bold text-foreground text-center mb-8">
        Frequently Asked Questions
      </h2>
      
      <Accordion type="single" collapsible className="max-w-2xl mx-auto">
        {faqs.map((faq, index) => (
          <AccordionItem key={index} value={`item-${index}`}>
            <AccordionTrigger className="text-left">
              {faq.question}
            </AccordionTrigger>
            <AccordionContent className="text-muted-foreground">
              {faq.answer}
            </AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>
    </section>
  );
}

import Lens from 'chrome-lens-ocr';
import express from 'express';
import cors from 'cors';
import PQueue from 'p-queue';
import crypto from 'crypto';
import rateLimit from 'express-rate-limit';
import os from 'os';
import { Builder, By, Key, until } from 'selenium-webdriver';
import chrome from 'selenium-webdriver/chrome.js';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
import { dirname } from 'path';
import clipboardy from 'clipboardy';

// Resolva o diretório atual
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const app = express();
const lens = new Lens();
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ extended: true }));
app.use(cors());

// Limitação de taxa: 100 requisições por minuto por IP
const limiter = rateLimit({
  windowMs: 60 * 1000, // 1 minuto
  max: 100, // Limita a 100 requisições por IP
  message: 'Muitas requisições, tente novamente mais tarde.',
});
app.use(limiter);

// Função para gerar um hash único para a imagem
function generateImageHash(imageBase64) {
  const hash = crypto.createHash('sha256');
  hash.update(imageBase64);
  return hash.digest('hex');
}

// Cache de resultados OCR (em memória)
const cache = new Map();

// Fila de jobs com concorrência dinâmica (até o número de CPUs do servidor)
const queue = new PQueue({ concurrency: Math.min(5, Math.max(1, os.cpus().length)) });

// Função que processa o OCR a partir da imagem em Base64
// Função que processa o OCR a partir da imagem em Base64
// Função que processa o OCR a partir da imagem em Base64
async function processOcr(imageBase64, driver) {
  const imageHash = generateImageHash(imageBase64);

  // Verifica se o resultado já está no cache
  if (cache.has(imageHash)) {
    console.log('Usando cache');
    return cache.get(imageHash);
  }

  const base64Data = imageBase64.replace(/^data:image\/\w+;base64,/, '');
  const buffer = Buffer.from(base64Data, 'base64');

  try {
    // Tentativa de OCR com Lens
    const ocrResult = await lens.scanByBuffer(buffer);

    const placaRegex = /[A-Z]{3}[0-9][A-Z][0-9]{2}|[A-Z]{3}-[0-9]{4}/g;
    let textoExtraido = ocrResult?.segments?.map(seg => seg.text).join(' ') || ocrResult.text || '';
    let placas = [...textoExtraido.matchAll(placaRegex)].map(match => match[0]);

    // Armazena o resultado no cache
    cache.set(imageHash, placas);

    // Se o resultado do Lens for vazio, tenta o OCR com Selenium
    if (placas.length === 0) {
      console.log('Placas não encontradas com Lens. Tentando OCR com Selenium...');
      placas = await extractPlateWithSelenium(imageBase64);
    }
    
    return placas;
  } catch (error) {
    console.error('Erro durante o OCR com Lens:', error.message);

    // Caso o OCR com Lens falhe, tenta o OCR com Selenium diretamente
    console.log('Tentando OCR com Selenium...');
    try {
      const placasSelenium = await extractPlateWithSelenium(imageBase64);
      return placasSelenium;  // Retorna as placas do Selenium
    } catch (seleniumError) {
      console.error('Erro no OCR com Selenium:', seleniumError.message);
      return [];  // Retorna um array vazio se ambos os OCRs falharem
    }
  }
}

function encontrarPlaca(clipboardText, maxTentativas = 3) {
  const horarioPattern = /\b\d{2}\/\d{2}\/\d{4} \d{2} \d{2} \d{2}\b/;
  if (horarioPattern.test(clipboardText)) {
      console.log("Horário encontrado no texto da placa. Ignorando esta placa e passando para a próxima imagem.");
      return null;
  }

  // Separa o texto em tokens alfanuméricos
  const tokens = clipboardText.match(/\w+/g) || [];
  let candidate = null;

  // Primeiro, tenta encontrar um token único com 6 a 8 caracteres que contenha números
  for (const token of tokens) {
      if (token.length >= 6 && token.length <= 8 && /\d/.test(token)) {
          candidate = token;
          break;
      }
  }

  // Se não encontrou, tenta juntar pares de tokens consecutivos
  if (!candidate && tokens.length >= 2) {
      for (let i = 0; i < tokens.length - 1; i++) {
          const combined = tokens[i] + tokens[i + 1];
          if (combined.length >= 6 && combined.length <= 8 && /\d/.test(combined)) {
              candidate = combined;
              break;
          }
      }
  }

  if (candidate) {
      // Se o candidato tiver 8 caracteres, verifique se ao remover o primeiro caractere ainda há números.
      if (candidate.length === 8 && /\d/.test(candidate.slice(1))) {
          candidate = candidate.slice(1);
      }
      // Se a placa resultante tiver 6 ou 7 caracteres, aceite-a.
      if (candidate.length >= 6 && candidate.length <= 7) {
          return candidate;
      } else {
          console.log("Texto extraído não se enquadra no tamanho esperado. Tentando novamente...");
      }
  } else {
      console.log("Nenhuma placa válida encontrada. Tentando novamente...");
  }

  return null; // Retorna null se não encontrar uma placa válida
}

// Função para tentar extrair a placa com o Selenium, caso o OCR falhe
async function extractPlateWithSelenium(imageBase64) {
  let driver;
  let attempt = 0;
  const maxAttempts = 2; // Limite de tentativas no Selenium
  let placas = [];
  
  while (attempt < maxAttempts && placas.length === 0) {
    attempt++;
    try {
      // Configuração do Selenium
      driver = await new Builder()
        .forBrowser('chrome')
        .setChromeOptions(new chrome.Options())
        .build();

      // Acessa o Bing Visual Search
      await driver.get('https://www.bing.com/visualsearch');
      await driver.sleep(2000);

      // Salva a imagem temporariamente
      const imageHash = generateImageHash(imageBase64);
      const filePath = path.join(__dirname, 'temp_image.png'); // Salva a imagem temporariamente
      const buffer = Buffer.from(imageBase64, 'base64');
      fs.writeFileSync(filePath, buffer);

      await driver.sleep(1500);
      await driver.findElement(By.xpath("//a[contains(text(),'Aceitar')]")).click();
      
      // Carregar a imagem diretamente no Bing Visual Search
      const uploadButton = await driver.findElement(By.css('input[type="file"]'));
      await uploadButton.sendKeys(filePath);

      // Aguardar o processamento da imagem
      await driver.sleep(2500);

      // Verificar o resultado do OCR no Bing
      try {
        await driver.findElement(By.xpath("//span[contains(text(),'Texto')]")).click();
        
        await driver.sleep(1500);

        const copiedText = await driver.findElement(By.xpath("//div[contains(@class, 'text_copy_btn')]"));

        await copiedText.click();

        const clipboardContent = await clipboardy.read();
        const placa = encontrarPlaca(clipboardContent);

        return placa;
      } catch (error) {
        console.error('Erro ao tentar obter o resultado do OCR:', error.message);
        continue; // Tenta novamente
      }
    } catch (error) {
      console.error('Erro no Selenium:', error.message);
      break; // Se der erro, interrompe o loop
    } finally {
      if (driver) {
        await driver.quit(); // Fecha o driver após cada tentativa
      }
    }
  }

  // Retorna as placas encontradas ou um array vazio caso não consiga
  return placas;
}
// Rota Express que adiciona o job na fila e aguarda o resultado
app.post('/ocr', async (req, res) => {
  const { imageBase64 } = req.body;
  if (!imageBase64) {
    return res.status(400).json({ error: 'Campo imageBase64 é obrigatório.' });
  }

  try {
    const startTime = Date.now();
    
    // Adiciona o job à fila e aguarda sua conclusão
    const placas = await queue.add(() => processOcr(imageBase64));

    const endTime = Date.now();
    
    res.json({
      placas,
      metadata: {
        processingTime: endTime - startTime, // Tempo de processamento
        timestamp: new Date().toISOString(), // Hora da solicitação
      },
    });
  } catch (error) {
    console.error('Erro no OCR:', error.message);
    res.status(500).json({ error: 'Erro ao processar OCR.', details: error.message });
  }
});

// Inicia o servidor na porta 8082
app.listen(8082, () => console.log('Servidor OCR rodando na porta 8082'));

package se.tools;

import org.w3c.dom.*;
import org.xml.sax.EntityResolver;
import org.xml.sax.InputSource;
import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.transform.OutputKeys;
import javax.xml.transform.Transformer;
import javax.xml.transform.TransformerFactory;
import javax.xml.transform.dom.DOMSource;
import javax.xml.transform.stream.StreamResult;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.zip.GZIPInputStream;
import java.util.zip.GZIPOutputStream;

public class scenarios {

    private static final double EV_ADOPTION_PCT = 50.0;   // percent of candidate EVs kept
    private static final double HOME_ACCESS_SHARE = 0.80;
    private static final double WORK_ACCESS_SHARE = 0.80;
    private static final double VIPV_SHARE = 0.50;        // among adopted EVs

    private static final String HOME_POWER = "7";
    private static final String WORK_POWER = "11";

    private static final double RANGE_MIN = 0.15;
    private static final double RANGE_MAX = 0.35;
    private static final int RANGE_DECIMALS = 2;

    // VIPV CSV metadata columns
    private static final double PV_WP = 400.0;
    private static final double PV_AREA_M2 = 2.0;
    private static final double PV_EFF = 0.20;

    private static final long MASTER_SEED = 42L;
    private static final Path SWEDEN_ROOT = Paths.get("scenarios", "sweden");

    private static final Set<String> EV_ATTR_NAMES = new HashSet<>(
            Arrays.asList("rangeAnxietyThreshold", "homeChargerPower", "workChargerPower")
    );

    public static void main(String[] args) throws Exception {
        checkRoot();
        List<SampleSpec> samples = Arrays.asList(
                new SampleSpec("1pct", "GOTplans_1pct7Days.xml.gz", "evehicles1pct.xml"),
                new SampleSpec("10pct", "GOTplans_10pct7Days.xml.gz", "evehicles10pct.xml")
        );

        for (SampleSpec sample : samples) {
            processSample(sample);
            System.out.println();
        }

        System.out.println("Done.");
    }

    private static void processSample(SampleSpec sample) throws Exception {
        Path sampleDir = SWEDEN_ROOT.resolve(sample.folderName);
        Path plansPath = sampleDir.resolve(sample.basePlansFile);
        Path baseEvPath = sampleDir.resolve(sample.baseEvFile);

        if (!Files.exists(plansPath)) {
            throw new FileNotFoundException("Plans file not found: " + plansPath.toAbsolutePath());
        }
        if (!Files.exists(baseEvPath)) {
            throw new FileNotFoundException("Base EV file not found: " + baseEvPath.toAbsolutePath());
        }

        Document plansDoc = parseXml(plansPath);
        Document evDoc = parseXml(baseEvPath);
        List<Element> baseVehicles = getChildElementsByTag(evDoc.getDocumentElement(), "vehicle");
        List<String> candidateEvIds = new ArrayList<>();
        for (Element v : baseVehicles) {
            String id = v.getAttribute("id");
            if (id != null && !id.isEmpty()) {
                candidateEvIds.add(id);
            }
        }

        if (candidateEvIds.isEmpty()) {
            throw new IllegalStateException("No EV vehicle ids found in " + baseEvPath);
        }

        List<Element> persons = getChildElementsByTag(plansDoc.getDocumentElement(), "person");
        Set<String> personIds = new HashSet<>();
        for (Element p : persons) {
            personIds.add(p.getAttribute("id"));
        }

        // Keep only EV ids that actually exist in plans
        List<String> validCandidateEvIds = new ArrayList<>();
        for (String id : candidateEvIds) {
            if (personIds.contains(id)) {
                validCandidateEvIds.add(id);
            }
        }

        int candidateCount = validCandidateEvIds.size();
        int adoptCount = boundedCount(candidateCount, EV_ADOPTION_PCT / 100.0);
        int vipvCount = boundedCount(adoptCount, VIPV_SHARE);
        int homeCountTarget = boundedCount(adoptCount, HOME_ACCESS_SHARE);
        int workCountTarget = boundedCount(adoptCount, WORK_ACCESS_SHARE);
        Random adoptionRng = new Random(seedFor(sample.folderName, "adoption"));
        Random homeRng = new Random(seedFor(sample.folderName, "home"));
        Random workRng = new Random(seedFor(sample.folderName, "work"));
        Random vipvRng = new Random(seedFor(sample.folderName, "vipv"));
        Random rangeRng = new Random(seedFor(sample.folderName, "range"));

        Set<String> adoptedIds = sampleSet(validCandidateEvIds, adoptCount, adoptionRng);
        List<String> adoptedIdList = new ArrayList<>(adoptedIds);
        Collections.sort(adoptedIdList);
        Set<String> homeIds = sampleSet(adoptedIdList, homeCountTarget, homeRng);
        Set<String> workIds = sampleSet(adoptedIdList, workCountTarget, workRng);
        Set<String> vipvIds = sampleSet(adoptedIdList, vipvCount, vipvRng);

        // Write adopted EV file
        Document adoptedEvDoc = newEmptyDocument();
        Element vehiclesRoot = adoptedEvDoc.createElement("vehicles");
        adoptedEvDoc.appendChild(vehiclesRoot);

        int writtenEvCount = 0;
        for (Element v : baseVehicles) {
            String id = v.getAttribute("id");
            if (adoptedIds.contains(id)) {
                Node imported = adoptedEvDoc.importNode(v, true);
                vehiclesRoot.appendChild(imported);
                writtenEvCount++;
            }
        }

        int adoptPctInt = (int) Math.round(EV_ADOPTION_PCT);
        int vipvPctInt = (int) Math.round(VIPV_SHARE * 100.0);

        Path outEvPath = sampleDir.resolve(String.format("evehicles%s_%dadopt.xml.gz", sample.folderName, adoptPctInt));
        writeXml(adoptedEvDoc, outEvPath, "http://matsim.org/files/dtd/electric_vehicles_v1.dtd");

        // Rewrite plans with EV-only attributes
        Stats stats = rewritePlans(plansDoc, adoptedIds, homeIds, workIds, rangeRng);
        Path outPlansPath = sampleDir.resolve(String.format("GOTplans_%s7Days_EV%d.xml.gz", sample.folderName, adoptPctInt));
        writeXml(plansDoc, outPlansPath, "http://www.matsim.org/files/dtd/population_v6.dtd");

        // Write VIPV CSV
        Path outVipvCsv = sampleDir.resolve(String.format("%dVIPV_%s.csv", vipvPctInt, sample.folderName));
        writeVipvCsv(outVipvCsv, vipvIds);

        System.out.println("====================================================");
        System.out.println("Sample: " + sample.folderName);
        System.out.println("Base plans: " + plansPath);
        System.out.println("Base EV file: " + baseEvPath);
        System.out.println("Output plans: " + outPlansPath.getFileName());
        System.out.println("Output EV file: " + outEvPath.getFileName());
        System.out.println("Output VIPV CSV: " + outVipvCsv.getFileName());
        System.out.println();
        System.out.println("Candidate EV ids in base EV file: " + candidateEvIds.size());
        System.out.println("Candidate EV ids also present in plans: " + candidateCount);
        System.out.println("Adopted EV target percent: " + EV_ADOPTION_PCT + "%");
        System.out.println("Adopted EV count: " + writtenEvCount);
        System.out.println("VIPV share among adopted EVs: " + (VIPV_SHARE * 100.0) + "%");
        System.out.println("VIPV count: " + vipvIds.size());
        System.out.println("Home access target share among adopted EVs: " + (HOME_ACCESS_SHARE * 100.0) + "%");
        System.out.println("Work access target share among adopted EVs: " + (WORK_ACCESS_SHARE * 100.0) + "%");
        System.out.println("Observed adopted EVs with home charger access: " + stats.evWithHome + " (" + pct(stats.evWithHome, stats.adoptedEvPersons) + "%)");
        System.out.println("Observed adopted EVs with work charger access: " + stats.evWithWork + " (" + pct(stats.evWithWork, stats.adoptedEvPersons) + "%)");
        System.out.println("Observed adopted EVs with both: " + stats.evWithBoth + " (" + pct(stats.evWithBoth, stats.adoptedEvPersons) + "%)");
        System.out.println("Observed adopted EVs with neither: " + stats.evWithNeither + " (" + pct(stats.evWithNeither, stats.adoptedEvPersons) + "%)");
        System.out.println("Range anxiety assigned to adopted EVs:");
        System.out.println("  min = " + String.format(Locale.US, "%." + RANGE_DECIMALS + "f", stats.minRangeAnxiety));
        System.out.println("  max = " + String.format(Locale.US, "%." + RANGE_DECIMALS + "f", stats.maxRangeAnxiety));
        System.out.println("Persons in plans: " + stats.totalPersons);
        System.out.println("Adopted EV persons updated: " + stats.adoptedEvPersons);
        System.out.println("Non-EV persons cleaned of EV-specific attrs: " + stats.nonEvCleaned);
        System.out.println("====================================================");
    }

    private static Stats rewritePlans(Document plansDoc,
                                      Set<String> adoptedIds,
                                      Set<String> homeIds,
                                      Set<String> workIds,
                                      Random rangeRng) {
        Stats stats = new Stats();
        Element populationRoot = plansDoc.getDocumentElement();
        List<Element> persons = getChildElementsByTag(populationRoot, "person");
        stats.totalPersons = persons.size();
        stats.minRangeAnxiety = Double.POSITIVE_INFINITY;
        stats.maxRangeAnxiety = Double.NEGATIVE_INFINITY;

        for (Element person : persons) {
            String pid = person.getAttribute("id");
            boolean isAdoptedEv = adoptedIds.contains(pid);

            if (!isAdoptedEv) {
                boolean cleaned = removeEvSpecificAttributes(person);
                if (cleaned) {
                    stats.nonEvCleaned++;
                }
                continue;
            }

            stats.adoptedEvPersons++;

            Element attrsEl = getOrCreateAttributesElement(plansDoc, person);

            // Always overwrite EV-specific attrs for adopted EVs
            removeNamedAttributes(attrsEl, EV_ATTR_NAMES);

            double rangeVal = roundedUniform(rangeRng, RANGE_MIN, RANGE_MAX, RANGE_DECIMALS);
            setAttribute(plansDoc, attrsEl, "rangeAnxietyThreshold", String.format(Locale.US, "%." + RANGE_DECIMALS + "f", rangeVal));

            boolean hasHome = homeIds.contains(pid);
            boolean hasWork = workIds.contains(pid);

            if (hasHome) {
                setAttribute(plansDoc, attrsEl, "homeChargerPower", HOME_POWER);
                stats.evWithHome++;
            }
            if (hasWork) {
                setAttribute(plansDoc, attrsEl, "workChargerPower", WORK_POWER);
                stats.evWithWork++;
            }
            if (hasHome && hasWork) {
                stats.evWithBoth++;
            }
            if (!hasHome && !hasWork) {
                stats.evWithNeither++;
            }

            stats.minRangeAnxiety = Math.min(stats.minRangeAnxiety, rangeVal);
            stats.maxRangeAnxiety = Math.max(stats.maxRangeAnxiety, rangeVal);
        }

        if (stats.adoptedEvPersons == 0) {
            stats.minRangeAnxiety = 0.0;
            stats.maxRangeAnxiety = 0.0;
        }

        return stats;
    }

    private static void writeVipvCsv(Path outputPath, Set<String> vipvIds) throws IOException {
        Files.createDirectories(outputPath.getParent());
        List<String> sorted = new ArrayList<>(vipvIds);
        sorted.sort(
                Comparator.comparingLong((String s) -> {
                    try {
                        return Long.parseLong(s);
                    } catch (Exception e) {
                        return Long.MAX_VALUE;
                    }
                }).thenComparing(String::compareTo)
        );

        try (BufferedWriter w = Files.newBufferedWriter(outputPath, StandardCharsets.UTF_8)) {
            w.write("vehicle_id,pv_wp,pv_area_m2,pv_eff");
            w.newLine();
            for (String id : sorted) {
                w.write(id + "," + PV_WP + "," + PV_AREA_M2 + "," + PV_EFF);
                w.newLine();
            }
        }
    }

    private static void writeXml(Document doc, Path outputPath, String doctypeSystem) throws Exception {
        Files.createDirectories(outputPath.getParent());

        TransformerFactory tf = TransformerFactory.newInstance();
        try {
            tf.setAttribute("indent-number", 2);
        } catch (Exception ignored) {
        }

        Transformer transformer = tf.newTransformer();
        transformer.setOutputProperty(OutputKeys.ENCODING, "UTF-8");
        transformer.setOutputProperty(OutputKeys.INDENT, "yes");
        transformer.setOutputProperty(OutputKeys.METHOD, "xml");
        transformer.setOutputProperty(OutputKeys.DOCTYPE_SYSTEM, doctypeSystem);
        try {
            transformer.setOutputProperty("{http://xml.apache.org/xslt}indent-amount", "2");
        } catch (Exception ignored) {
        }

        OutputStream os = Files.newOutputStream(outputPath);
        if (outputPath.toString().endsWith(".gz")) {
            os = new GZIPOutputStream(os);
        }

        try (OutputStream out = os;
             Writer writer = new OutputStreamWriter(out, StandardCharsets.UTF_8)) {
            transformer.transform(new DOMSource(doc), new StreamResult(writer));
        }
    }

    private static Document parseXml(Path path) throws Exception {
        DocumentBuilderFactory dbf = DocumentBuilderFactory.newInstance();
        dbf.setNamespaceAware(false);
        dbf.setValidating(false);
        safeSetFeature(dbf, "http://xml.org/sax/features/validation", false);
        safeSetFeature(dbf, "http://apache.org/xml/features/nonvalidating/load-external-dtd", false);
        safeSetFeature(dbf, "http://xml.org/sax/features/external-general-entities", false);
        safeSetFeature(dbf, "http://xml.org/sax/features/external-parameter-entities", false);

        DocumentBuilder db = dbf.newDocumentBuilder();
        EntityResolver noOpResolver = (publicId, systemId) -> new InputSource(new StringReader(""));
        db.setEntityResolver(noOpResolver);

        try (InputStream fis = Files.newInputStream(path);
             InputStream is = path.toString().endsWith(".gz") ? new GZIPInputStream(fis) : fis) {
            return db.parse(is);
        }
    }

    private static Document newEmptyDocument() throws Exception {
        DocumentBuilderFactory dbf = DocumentBuilderFactory.newInstance();
        DocumentBuilder db = dbf.newDocumentBuilder();
        return db.newDocument();
    }

    private static Element getOrCreateAttributesElement(Document doc, Element person) {
        List<Element> directChildren = getDirectChildElements(person);
        for (Element child : directChildren) {
            if ("attributes".equals(child.getTagName())) {
                return child;
            }
        }

        Element attrs = doc.createElement("attributes");

        Node firstPlan = null;
        for (Element child : directChildren) {
            if ("plan".equals(child.getTagName())) {
                firstPlan = child;
                break;
            }
        }

        if (firstPlan != null) {
            person.insertBefore(attrs, firstPlan);
        } else {
            person.appendChild(attrs);
        }
        return attrs;
    }

    private static boolean removeEvSpecificAttributes(Element person) {
        Element attrsEl = null;
        for (Element child : getDirectChildElements(person)) {
            if ("attributes".equals(child.getTagName())) {
                attrsEl = child;
                break;
            }
        }
        if (attrsEl == null) {
            return false;
        }

        int before = attrsEl.getChildNodes().getLength();
        removeNamedAttributes(attrsEl, EV_ATTR_NAMES);

        boolean hasAnyAttributeElements = false;
        NodeList children = attrsEl.getChildNodes();
        for (int i = 0; i < children.getLength(); i++) {
            Node n = children.item(i);
            if (n instanceof Element && "attribute".equals(((Element) n).getTagName())) {
                hasAnyAttributeElements = true;
                break;
            }
        }

        if (!hasAnyAttributeElements) {
            person.removeChild(attrsEl);
        }

        int after = attrsEl.getChildNodes().getLength();
        return before != after || !hasAnyAttributeElements;
    }

    private static void removeNamedAttributes(Element attrsEl, Set<String> names) {
        List<Element> attrs = getChildElementsByTag(attrsEl, "attribute");
        for (Element a : attrs) {
            String name = a.getAttribute("name");
            if (names.contains(name)) {
                attrsEl.removeChild(a);
            }
        }
    }

    private static void setAttribute(Document doc, Element attrsEl, String name, String value) {
        Element a = doc.createElement("attribute");
        a.setAttribute("name", name);
        a.setAttribute("class", "java.lang.String");
        a.appendChild(doc.createTextNode(value));
        attrsEl.appendChild(a);
    }

    private static List<Element> getChildElementsByTag(Element parent, String tagName) {
        List<Element> out = new ArrayList<>();
        NodeList nl = parent.getElementsByTagName(tagName);
        for (int i = 0; i < nl.getLength(); i++) {
            Node n = nl.item(i);
            if (n instanceof Element) {
                out.add((Element) n);
            }
        }
        return out;
    }

    private static List<Element> getDirectChildElements(Element parent) {
        List<Element> out = new ArrayList<>();
        NodeList nl = parent.getChildNodes();
        for (int i = 0; i < nl.getLength(); i++) {
            Node n = nl.item(i);
            if (n instanceof Element) {
                out.add((Element) n);
            }
        }
        return out;
    }

    private static Set<String> sampleSet(List<String> ids, int n, Random rng) {
        List<String> copy = new ArrayList<>(ids);
        Collections.shuffle(copy, rng);
        int k = Math.max(0, Math.min(n, copy.size()));
        return new HashSet<>(copy.subList(0, k));
    }

    private static int boundedCount(int total, double share) {
        return Math.max(0, Math.min(total, (int) Math.round(total * share)));
    }

    private static double roundedUniform(Random rng, double min, double max, int decimals) {
        double raw = min + (max - min) * rng.nextDouble();
        double scale = Math.pow(10, decimals);
        return Math.round(raw * scale) / scale;
    }

    private static long seedFor(String folderName, String stream) {
        return MASTER_SEED + 31L * folderName.hashCode() + 1009L * stream.hashCode();
    }

    private static String pct(int num, int den) {
        if (den == 0) return "0.00";
        return String.format(Locale.US, "%.2f", 100.0 * num / den);
    }

    private static void safeSetFeature(DocumentBuilderFactory dbf, String feature, boolean value) {
        try {
            dbf.setFeature(feature, value);
        } catch (Exception ignored) {
        }
    }

    private static void checkRoot() {
        if (!Files.isDirectory(SWEDEN_ROOT)) {
            throw new IllegalStateException(
                    "Could not find clone-relative scenario root: " + SWEDEN_ROOT.toAbsolutePath() +
                            "\nRun this class from the project root, or change SWEDEN_ROOT."
            );
        }
    }

    private static final class SampleSpec {
        final String folderName;
        final String basePlansFile;
        final String baseEvFile;

        SampleSpec(String folderName, String basePlansFile, String baseEvFile) {
            this.folderName = folderName;
            this.basePlansFile = basePlansFile;
            this.baseEvFile = baseEvFile;
        }
    }

    private static final class Stats {
        int totalPersons;
        int adoptedEvPersons;
        int nonEvCleaned;
        int evWithHome;
        int evWithWork;
        int evWithBoth;
        int evWithNeither;
        double minRangeAnxiety;
        double maxRangeAnxiety;
    }
}
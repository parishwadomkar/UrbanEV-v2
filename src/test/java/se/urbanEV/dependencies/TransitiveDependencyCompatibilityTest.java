package se.urbanEV.dependencies;

import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.core.StreamReadConstraints;
import com.fasterxml.jackson.core.exc.StreamConstraintsException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.google.common.collect.ImmutableList;
import com.google.common.util.concurrent.SettableFuture;
import com.google.inject.AbstractModule;
import com.google.inject.Guice;
import com.google.inject.Key;
import com.google.inject.TypeLiteral;
import net.jpountz.lz4.LZ4Factory;
import net.jpountz.xxhash.XXHashFactory;
import org.apache.commons.beanutils.BeanUtils;
import org.apache.commons.beanutils.PropertyUtils;
import org.hibernate.validator.constraints.UniqueElements;
import org.jdom2.Document;
import org.jdom2.input.SAXBuilder;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.matsim.core.utils.io.IOUtils;

import javax.validation.Constraint;
import javax.validation.ConstraintValidator;
import javax.validation.ConstraintValidatorContext;
import javax.validation.Payload;
import javax.validation.Validation;
import javax.validation.ValidatorFactory;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.StringReader;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;

class TransitiveDependencyCompatibilityTest {
    @TempDir
    Path temporaryDirectory;

    @Test
    void jacksonRoundTripsScenarioMetadata() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        JsonNode expected = mapper.createObjectNode()
                .put("scenario", "VIPV50_Wp700")
                .put("city", "Gothenburg")
                .put("capacity_kWh", 10.5);
        assertEquals(expected, mapper.readTree(mapper.writeValueAsBytes(expected)));
    }

    @Test
    void jacksonEnforcesConfiguredNestingLimit() {
        JsonFactory factory = JsonFactory.builder()
                .streamReadConstraints(StreamReadConstraints.builder().maxNestingDepth(8).build())
                .build();
        ObjectMapper mapper = new ObjectMapper(factory);
        String nested = "[".repeat(9) + "0" + "]".repeat(9);
        assertThrows(StreamConstraintsException.class, () -> mapper.readTree(nested));
    }

    @Test
    void jdomParsesScenarioXml() throws Exception {
        SAXBuilder builder = new SAXBuilder();
        Document document = builder.build(new StringReader(
                "<scenario id=\"noVIPV\"><capacity>15</capacity></scenario>"));
        assertEquals("noVIPV", document.getRootElement().getAttributeValue("id"));
        assertEquals("15", document.getRootElement().getChildText("capacity"));
    }

    @Test
    void beanPropertiesRemainUsableWithoutClassLoaderAccess() throws Exception {
        CapacityBean source = new CapacityBean();
        source.setCapacity(15);
        CapacityBean destination = new CapacityBean();
        BeanUtils.copyProperties(destination, source);
        assertEquals(15, destination.getCapacity());
        assertFalse(PropertyUtils.isReadable(source, "class"));
        assertThrows(NoSuchMethodException.class,
                () -> PropertyUtils.getProperty(ExampleScenario.NO_VIPV, "declaringClass"));
    }

    @Test
    void guiceBindingsAndGuavaFuturesRemainCompatible() throws Exception {
        Key<List<String>> key = Key.get(new TypeLiteral<List<String>>() { });
        List<String> expected = ImmutableList.of("noVIPV", "VIPV50_Wp700");
        List<String> actual = Guice.createInjector(new AbstractModule() {
            @Override
            protected void configure() {
                bind(key).toInstance(expected);
            }
        }).getInstance(key);
        assertEquals(expected, actual);
        SettableFuture<List<String>> future = SettableFuture.create();
        future.set(actual);
        assertEquals(expected, future.get());
    }

    @Test
    void customValidationMessagesDoNotEvaluateExpressionLanguage() {
        try (ValidatorFactory factory = Validation.buildDefaultValidatorFactory()) {
            var violations = factory.getValidator().validate(new ValidationInput());
            assertEquals(1, violations.size());
            assertEquals("${1+1}", violations.iterator().next().getMessage());
        }
    }

    @Test
    void constraintMessageParametersRemainLiteral() {
        try (ValidatorFactory factory = Validation.buildDefaultValidatorFactory()) {
            var violations = factory.getValidator().validate(new DuplicateInput());
            assertEquals(1, violations.size());
            assertEquals("${1+1}", violations.iterator().next().getMessage());
        }
    }

    @Test
    void lz4JavaAndNativeImplementationsRoundTrip() {
        byte[] expected = "MATSim charging events and VIPV metadata\n".repeat(100)
                .getBytes(StandardCharsets.UTF_8);
        for (LZ4Factory factory : new LZ4Factory[]{LZ4Factory.safeInstance(), LZ4Factory.nativeInstance()}) {
            byte[] compressed = factory.fastCompressor().compress(expected);
            byte[] actual = new byte[expected.length];
            int length = factory.safeDecompressor().decompress(
                    compressed, 0, compressed.length, actual, 0, actual.length);
            assertEquals(expected.length, length);
            assertArrayEquals(expected, actual);
        }
        int javaHash = XXHashFactory.safeInstance().hash32().hash(expected, 0, expected.length, 0);
        int nativeHash = XXHashFactory.nativeInstance().hash32().hash(expected, 0, expected.length, 0);
        assertEquals(javaHash, nativeHash);
    }

    @Test
    void matsimCompressionStreamsRemainReadable() throws Exception {
        byte[] expected = "<events><event time=\"0\" type=\"charging\"/></events>\n"
                .repeat(50).getBytes(StandardCharsets.UTF_8);
        for (String extension : new String[]{".xml", ".xml.gz", ".xml.bz2", ".xml.lz4"}) {
            var url = temporaryDirectory.resolve("events" + extension).toUri().toURL();
            try (OutputStream output = IOUtils.getOutputStream(url, false)) {
                output.write(expected);
            }
            try (InputStream input = IOUtils.getInputStream(url)) {
                assertArrayEquals(expected, input.readAllBytes());
            }
        }
    }

    public enum ExampleScenario {
        NO_VIPV
    }

    public static class CapacityBean {
        private int capacity;

        public int getCapacity() {
            return capacity;
        }

        public void setCapacity(int capacity) {
            this.capacity = capacity;
        }
    }

    @Constraint(validatedBy = LiteralMessageValidator.class)
    @Target(ElementType.FIELD)
    @Retention(RetentionPolicy.RUNTIME)
    public @interface LiteralMessage {
        String message() default "{se.urbanEV.dependencies.LiteralMessage.message}";
        Class<?>[] groups() default {};
        Class<? extends Payload>[] payload() default {};
    }

    public static class LiteralMessageValidator implements ConstraintValidator<LiteralMessage, String> {
        @Override
        public boolean isValid(String value, ConstraintValidatorContext context) {
            context.disableDefaultConstraintViolation();
            context.buildConstraintViolationWithTemplate(value).addConstraintViolation();
            return false;
        }
    }

    public static class DuplicateInput {
        @UniqueElements(message = "{duplicates}")
        public List<String> values = List.of("${1+1}", "${1+1}");
    }

    public static class ValidationInput {
        @LiteralMessage
        public String message = "${1+1}";
    }
}

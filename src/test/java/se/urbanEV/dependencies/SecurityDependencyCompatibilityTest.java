package se.urbanEV.dependencies;

import java.util.Map;
import org.apache.commons.text.StringEscapeUtils;
import org.apache.commons.text.StringSubstitutor;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.core.LoggerContext;
import org.geotools.referencing.CRS;
import org.junit.jupiter.api.Test;
import org.opengis.referencing.crs.CoordinateReferenceSystem;
import org.opengis.referencing.operation.MathTransform;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class SecurityDependencyCompatibilityTest {

    @Test
    void legacyAndModernLoggingLoadTheCoreImplementation() {
        assertTrue(LogManager.getContext(false) instanceof LoggerContext);
        assertDoesNotThrow(() -> LogManager.getLogger(getClass()).info("Logging compatibility check"));
        assertDoesNotThrow(() -> org.apache.log4j.Logger.getLogger(getClass()).info("Legacy logging compatibility check"));
    }

    @Test
    void textEscapingAndSubstitutionResolveTheirDependencies() {
        assertEquals("Gothenburg &amp; &lt;EV&gt;", StringEscapeUtils.escapeHtml4("Gothenburg & <EV>"));
        StringSubstitutor substitutor = new StringSubstitutor(Map.of("scenario", "noVIPV"));
        assertEquals("scenario=noVIPV", substitutor.replace("scenario=${scenario}"));
    }

    @Test
    void epsgDatabaseSupportsSwedishCoordinateRoundTrip() throws Exception {
        CoordinateReferenceSystem wgs84 = CRS.decode("EPSG:4326", true);
        CoordinateReferenceSystem sweref99 = CRS.decode("EPSG:3006", true);
        MathTransform forward = CRS.findMathTransform(wgs84, sweref99, true);
        double[] origin = {11.9746, 57.7089};
        double[] projected = new double[2];
        double[] restored = new double[2];
        forward.transform(origin, 0, projected, 0, 1);
        assertTrue(projected[0] > 100000 && projected[0] < 900000);
        assertTrue(projected[1] > 6000000 && projected[1] < 8000000);
        forward.inverse().transform(projected, 0, restored, 0, 1);
        assertArrayEquals(origin, restored, 1e-6);
    }
}
